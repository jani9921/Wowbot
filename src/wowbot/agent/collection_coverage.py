"""Partial snapshots are positive observations, never negative membership."""
from .models import json_copy


def prepare_collections(state, previous):
    """Return incoming quest rows and a complete-list flag before retaining history."""
    raw = state.get('active_quests')
    quests_valid = isinstance(raw, (list, tuple)) and all(isinstance(q, dict) for q in raw)
    incoming = json_copy([q for q in raw if isinstance(q, dict)]) if isinstance(raw, (list, tuple)) else []
    declared = state.get('collection_coverage')
    coverage = dict(declared) if isinstance(declared, dict) else None
    inventory_valid = isinstance(state.get('inventory'), dict)
    if coverage is not None:
        if not quests_valid:
            coverage['active_quests'] = 'UNKNOWN'
        if not inventory_valid:
            coverage['inventory'] = 'UNKNOWN'
    if (coverage is not None and coverage.get('quest_revision') is not None
            and state.get('quest_state_revision') is not None
            and coverage['quest_revision'] != state['quest_state_revision']):
        coverage['active_quests'] = 'PARTIAL'
    complete = quests_valid and (coverage is None or coverage.get('active_quests') == 'COMPLETE')
    if 'active_quests' in state:
        state['active_quests'] = json_copy(incoming)
    if state.get('loading') or state.get('player_present') is False:
        complete = False
    if not complete:
        old = {str(q.get('quest_id')): json_copy(q) for q in previous.get('active_quests') or () if isinstance(q, dict)}
        old.update({str(q.get('quest_id')): json_copy(q) for q in incoming if isinstance(q, dict)})
        if old:
            state['active_quests'] = list(old.values())
    if coverage is not None:
        for key in ('active_quests', 'inventory'):
            if key not in state or coverage.get(key) not in {'COMPLETE', 'PARTIAL', 'UNKNOWN'}:
                coverage[key] = 'UNKNOWN'
            if state.get('loading') or state.get('player_present') is False:
                coverage[key] = 'UNKNOWN'
        state['collection_coverage'] = coverage
    inventory = state.get('inventory')
    if coverage is not None and coverage.get('inventory') != 'COMPLETE':
        inventory = inventory if isinstance(inventory, dict) else {}
        old = previous.get('inventory') or {}
        state['inventory'] = {**json_copy(old), **inventory, 'complete': False}
    elif isinstance(inventory, dict) and coverage is not None:
        inventory['complete'] = True
    return incoming, complete


def inventory_ready(state):
    inventory = state.get('inventory') or {}
    if not isinstance(inventory, dict) or inventory.get('complete') is False:
        return False
    sampled, current = inventory.get('sample_time'), state.get('monotonic_time')
    return not (sampled is not None and current is not None and not 0 <= current-sampled <= 3.)


def quest_baseline_problem(state):
    coverage = state.get('collection_coverage')
    if not isinstance(coverage, dict):
        return None  # old replay compatibility; no packet/addon parity claim
    if coverage.get('active_quests') != 'COMPLETE':
        return 'questlog_baseline_incomplete'
    if any(o.get('objectives_coverage') not in (None, 'COMPLETE')
           for o in state.get('active_quests') or () if isinstance(o, dict) and not o.get('is_complete')):
        return 'quest_objectives_incomplete'
    return None
