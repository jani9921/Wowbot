"""Bounded observation settling after a confirmed own movement ability.

This only defers an out-of-range verdict; it grants no cast or movement
permission and never infers melee range from an ability's success.
"""
from wowbot.value_helpers import number


def settling_deadline(state, actions, expected_guid, now):
    target=state.get('target') or {}
    if (not expected_guid or target.get('guid')!=expected_guid
            or target.get('attackable',target.get('is_attackable')) is not True
            or target.get('dead',target.get('is_dead')) is True):
        return None
    spell=state.get('combat_last_spell_id')
    sampled=number(state.get('combat_last_cast_at'))
    current=number(now)
    if sampled is None or current is None or not 0<=current-sampled<1.:
        return None
    if any(a.get('is_harmful') is True and a.get('in_range') is True
           and 'MOVEMENT' not in a.get('tags',()) for a in actions):
        return None  # actual melee/ranged readiness wins immediately
    action=next((a for a in actions if a.get('id',a.get('spell_id'))==spell),None)
    if action is None or 'MOVEMENT' not in action.get('tags',()):
        return None
    seconds=number(action.get('movement_settle_seconds'))
    if seconds is None or not 0<seconds<=1. or current>=sampled+seconds:
        return None
    return sampled+seconds
