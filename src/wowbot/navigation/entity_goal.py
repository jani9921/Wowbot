"""Resolve the position of an explicit entity goal without changing its identity."""
from wowbot.value_helpers import number
from wowbot.runtime.entity_identity import check_entity_identity
from wowbot.runtime.skill_identity import sample_fresh
import math


def resolve(destination, state, now):
    if destination.get('entity_goal') is not True:
        return dict(destination)
    guid = destination.get('interaction_recipient_guid') or destination.get('target_guid')
    if not guid:
        return None
    if destination.get('interaction_identity_source') != 'SOFT_INTERACT':
        target = state.get('target') or {}
        if not check_entity_identity({'guid':guid}, target) or not sample_fresh(state, 'target', now):
            return None
        if target.get('dead', target.get('is_dead')) and not destination.get('allow_dead'):
            return None
    if destination.get('server_entity_guid'):
        from wowbot.agent.packet_entity_facts import interaction_position
        point = interaction_position(state, guid, allow_dead=destination.get('allow_dead') is True)
    else:
        point = (state.get('target') or {}).get('world_position')
    if not isinstance(point, dict) or any(number(point.get(k)) is None for k in ('x','y')):
        return None
    instance = (state.get('player_world_position') or {}).get('instance_id')
    if point.get('instance_id') is not None and instance is not None and str(point['instance_id']) != str(instance):
        return None
    result = {**destination, 'x':point['x'], 'y':point['y'], 'instance_id':point.get('instance_id')}
    z = number(point.get('z'))
    if z is not None and point.get('z_known') is not False and point.get('source') != 'UNIT_POSITION':
        result.update(z=z, z_known=True, layer_z=z)
    else:
        result.pop('z', None);result.pop('layer_z', None)
        result['z_known'] = False
    return result


# The smallest stop circle the controller can settle in: one minimum forward
# pulse mounted is ~0.56 yd, so a tighter circle would be overshot back and forth.
ANCHOR_TOLERANCE_FLOOR = .5


def anchor_tolerance(destination, anchor, desired_range):
    """A projected endpoint must not add a second interaction-radius margin.

    Within ``desired_range - offset`` of the anchor the target is within
    ``desired_range`` (triangle inequality).  An anchor farther off than that
    can only be reached, never brought into the band: ANCHOR_TOLERANCE_FLOOR."""
    x,y = number(anchor.get('x')),number(anchor.get('y'))
    tx,ty = number(destination.get('x')),number(destination.get('y'))
    if None in (x,y,tx,ty):
        return desired_range
    z,tz = number(anchor.get('z')),number(destination.get('z'))
    vertical = z-tz if None not in (z,tz) and destination.get('z_known') is True else 0.
    return max(ANCHOR_TOLERANCE_FLOOR,float(desired_range)-math.hypot(x-tx,y-ty,vertical))
