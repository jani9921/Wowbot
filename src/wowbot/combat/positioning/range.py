"""Desired sustained-attack range, never an ability-in-range permission."""
from wowbot.value_helpers import number


def engagement_range(actions, chosen, *, fallback=3.5):
    """A mobility opener cannot set the standing rotation's approach radius.

    Prefer the current non-movement action's documented positive envelope;
    after mobility, use the highest-priority bound offensive rotation action.
    Absent/zero envelopes keep the existing conservative approach default.
    Live readiness/range still decides whether any spell may be sent.
    """
    if 'MOVEMENT' not in chosen.tags:
        maximum=chosen.max_range
    else:
        candidates=[]
        for order,action in enumerate(actions):
            maximum=number(action.get('max_range'))
            if (action.get('kind')=='spell' and action.get('action')
                    and action.get('is_harmful') is True
                    and 'MOVEMENT' not in action.get('tags',())
                    and maximum is not None and maximum>0):
                candidates.append((number(action.get('combat_priority')) or 0.,-order,maximum))
        maximum=max(candidates)[2] if candidates else None
    return min(35.,max(2.,maximum*.8)) if maximum is not None and maximum>0 else fallback
