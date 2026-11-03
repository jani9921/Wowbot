"""Pure final-bearing assessment; no turn, retry, planner or input ownership."""
from dataclasses import asdict,dataclass
import math

from wowbot.entity_spatial import best_position
from wowbot.value_helpers import number


@dataclass(frozen=True,slots=True)
class FacingGeometry:
    reason: str
    source: str
    distance: float | None = None
    error: float | None = None
    desired_heading: float | None = None
    current_heading: float | None = None
    target_guid: str | None = None
    target_x: float | None = None
    target_y: float | None = None

    def snapshot(self):
        return asdict(self)


def assess(destination,state,position):
    point=destination.get('face_towards') or destination
    source='REQUEST_POINT'
    guid=destination.get('server_entity_guid')
    entities=state.get('packet_entities')
    if guid:
        source='SERVER_ENTITY'
        row=entities.get(str(guid)) if isinstance(entities,dict) else None
        if (not isinstance(row,dict) or row.get('removed')
                or row.get('guid') is not None and str(row['guid'])!=str(guid)):
            return FacingGeometry('ENTITY_UNKNOWN_OR_REMOVED',source,target_guid=str(guid))
        point=best_position(row)
        if point is None:
            return FacingGeometry('ENTITY_POSITION_UNKNOWN',source,target_guid=str(guid))
    elif destination.get('target_guid'):
        guid=destination['target_guid'];source='SELECTED_TARGET'
        target=state.get('target') or {}
        if str(target.get('guid') or '')!=str(guid):
            return FacingGeometry('SELECTED_IDENTITY_CHANGED',source,target_guid=str(guid))
        point=target.get('world_position')
    if not isinstance(point,dict):
        return FacingGeometry('POSITION_UNKNOWN',source,target_guid=str(guid) if guid else None)
    x,y,heading=number(point.get('x')),number(point.get('y')),number(state.get('orientation'))
    expected=(state.get('player_world_position') or {}).get('instance_id')
    instance=point.get('instance_id')
    if source=='SERVER_ENTITY' and (instance is None or expected is None):
        return FacingGeometry('WORLD_UNKNOWN',source,target_guid=str(guid))
    if instance is not None and expected is not None and str(instance)!=str(expected):
        return FacingGeometry('WORLD_MISMATCH',source,target_guid=str(guid) if guid else None)
    if (position is None or len(position)<2 or None in (x,y,heading)
            or any(number(v) is None for v in position[:2])):
        return FacingGeometry('POSE_UNKNOWN',source,target_guid=str(guid) if guid else None)
    dx,dy=x-position[0],y-position[1]
    desired=math.atan2(dy,dx)
    return FacingGeometry('KNOWN',source,math.hypot(dx,dy),
        (desired-heading+math.pi)%math.tau-math.pi,desired,heading,str(guid) if guid else None,x,y)
