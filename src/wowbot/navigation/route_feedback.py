"""Immutable post-query feedback prerequisite; NavigationService owns the wait."""
from dataclasses import asdict, dataclass
import math

from wowbot.value_helpers import number
from .position_acquisition import scope


def feedback_scope(state):
    legacy_map=state.get('map_id') if (state.get('player_world_position') or {}).get('instance_id') is None else None
    return (*scope(state),legacy_map,bool(state.get('is_dead')),bool(state.get('is_ghost')),bool(state.get('in_vehicle')))


def position(state, destination):
    point=(state.get('player_world_position') if destination.get('coordinate_space')=='WORLD_YARDS'
           else state.get('position')) or {}
    x,y=number(point.get('x')),number(point.get('y'))
    if None in (x,y):
        return None
    if destination.get('coordinate_space')=='WORLD_YARDS':
        z=number(point.get('observed_z'))
        z=z if z is not None else number(point.get('z')) if point.get('z_observed') is True else None
        return (x,y,z)
    return (x,y)


@dataclass(frozen=True,slots=True)
class RouteFeedback:
    request_id: str
    earliest_sample: float
    elapsed_seconds: float
    original_position: tuple | None
    context: tuple
    wait_seconds: float = 2.

    def assess(self,state,destination,now):
        if feedback_scope(state)!=self.context:
            return 'post_plan_feedback_context_changed'
        if state.get('loading') or state.get('input_blocked') or state.get('player_present') is False:
            return 'post_plan_feedback_interrupted'
        if now-self.earliest_sample>=self.wait_seconds:
            return 'post_plan_feedback_timeout'
        world=destination.get('coordinate_space')=='WORLD_YARDS'
        point=(state.get('player_world_position') if world else state.get('position')) or {}
        # A world position must carry its own measurement time: a newer merged
        # state repeating an old position is not post-plan feedback.
        sampled=number(point.get('sample_time') if world else point.get('sample_time',state.get('monotonic_time')))
        current=position(state,destination)
        if sampled is None or sampled<self.earliest_sample or sampled>now or current is None:
            return 'WAITING'
        if self.original_position is not None:
            vertical=0.
            if len(current)==3 and len(self.original_position)==3:
                if current[2] is not None and self.original_position[2] is None:
                    return 'REPLAN'
                if current[2] is not None and self.original_position[2] is not None:
                    vertical=current[2]-self.original_position[2]
            threshold=2. if destination.get('coordinate_space')=='WORLD_YARDS' else .003
            if math.hypot(current[0]-self.original_position[0],current[1]-self.original_position[1],vertical)>threshold:
                return 'REPLAN'
        return 'READY'

    def snapshot(self):
        return asdict(self)
