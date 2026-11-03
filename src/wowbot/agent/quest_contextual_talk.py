"""A reversible chat trial at the current objective's known local point.

No fixed dialogue phrase, quest ID, guessed NPC or new action authority.
Known combat, collection and object mechanics keep their normal handlers.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

from wowbot.query_ports import TravelCostPort
from .models import number, words
from .planning_types import world_point
from .quest_reference_matching import reference_objectives
from wowbot.runtime.entity_identity import guid_template, template_id

ARRIVAL_MECHANISMS = frozenset({'ARRIVE', 'TRAVEL_TO', 'REACH_AREA', 'UNKNOWN'})
LOCAL_YARDS = 10.
LOCAL_HEIGHT = 6.


def _local(point, other):
    xy = [number(row.get(k)) for row in (point, other) for k in ('x', 'y')]
    if None in xy or math.hypot(xy[0]-xy[2], xy[1]-xy[3]) > LOCAL_YARDS:
        return False
    if point.get('z_known') is True:
        z, other_z = number(point.get('z')), number(other.get('z'))
        if z is None or other_z is None or other.get('z_known') is False or abs(z-other_z) > LOCAL_HEIGHT:
            return False
    return True


def _objective_point(state, qid, objective, index, reference, *,
                     travel_cost: TravelCostPort | None = None):
    from .tdb_locations import objective_region
    oid = objective.get('objective_id') or f'{qid}:{index}'
    current_ids = {str(oid)}
    if objective.get('tdb_objective_id') is not None:
        current_ids.add(str(objective['tdb_objective_id']))
    current_ids.update(str(r.get('objective_id')) for r in reference_objectives(
        qid, oid, objective.get('description'), reference.get('objectives')))
    if any((str(p.get('objective_id')) in current_ids
            or not reference.get('objectives') and str(p.get('objective_index')) == str(index))
           and len(p.get('points') or ()) > 1
           and str(p.get('world_map_id')) == str((state.get('player_world_position') or {}).get('instance_id'))
           and str(p.get('ui_map_id')) == str(state.get('map_id')) for p in reference.get('pois') or ()):
        return None  # a multi-point search region does not prove a local meeting point
    row = SimpleNamespace(objective_id=oid, description=objective.get('description'),
                          target_location=objective.get('target_location'), completion_state='INCOMPLETE')
    # Reuse the existing TDB/live-POI agreement and current-objective resolver.
    point = objective_region(state, qid, row, travel_cost=travel_cost)
    if point is not None:
        return None if point.get('polygon_points') else point
    # With no static refinement, a single current client point is sufficient.
    # Do not choose between several objective points by list order.
    points = []
    for location in state.get('quest_locations') or ():
        if (not isinstance(location, dict) or str(location.get('quest_id')) != str(qid)
                or location.get('in_progress') is not True
                or str(location.get('role') or '').upper() in {'TURN_IN', 'QUEST_TURN_IN'}
                or location.get('source') == 'TASK_QUEST_POI'):
            continue
        explicit = location.get('objective_id')
        if explicit not in (None, '', 0, '0') and str(explicit) not in current_ids:
            continue
        value = world_point(location)
        if value is not None:
            points.append(value)
    distinct = {(p['instance_id'], p.get('map_id'), p['x'], p['y']): p for p in points}
    return next(iter(distinct.values())) if len(distinct) == 1 else None


def speakers_at_objective(state, qid, objective, reference, visible_units, *,
                          travel_cost: TravelCostPort | None = None):
    """Known quest giver + local objective point + live talkable actor."""
    quest = next((q for q in state.get('active_quests') or () if str(q.get('quest_id')) == str(qid)), {})
    objectives = quest.get('objectives') or ()
    index = next((i for i, row in enumerate(objectives) if row is objective), None)
    if index is None:
        return []
    oid = objective.get('objective_id') or f'{qid}:{index}'
    matched = reference_objectives(qid, oid, objective.get('description'), reference.get('objectives'))
    if len(matched) > 1 or any(row.get('objective_id') is None for row in matched):
        return []
    row = matched[0] if matched else {}
    mechanism = row.get('mechanism') or objective.get('mechanism') or objective.get('type')
    if (mechanism not in ARRIVAL_MECHANISMS or row.get('credit_action')
            or any(row.get(key) for key in ('named_creatures', 'talk_creatures', 'talk_actor_candidates',
                                           'spellclick_creatures', 'object_template', 'item_uses'))):
        return []
    point = _objective_point(state, qid, objective, index, reference, travel_cost=travel_cost)
    player = state.get('player_world_position') or {}
    if (point is None or str(point.get('instance_id')) != str(player.get('instance_id'))
            or str(point.get('map_id')) != str(state.get('map_id')) or not _local(point, player)):
        return []
    text = state.get('quest_text') or {}
    if str(text.get('quest_id')) == str(qid) and text.get('giver_guid'):
        giver = str(text['giver_guid'])
        entry = guid_template(giver).get('npc_id') if giver.startswith('Creature-') else None
        choices = ([{'entry': entry, 'name': text.get('giver_name')}] if entry is not None else [])
    else:
        roles = [r for r in reference.get('quest_roles') or () if isinstance(r, dict)
                 and r.get('role') in {'QUEST_STARTER', 'QUEST_ENDER'}
                 and template_id(r.get('npc_id')) is not None and r.get('name')]
        names = {words(str(r['name'])).strip() for r in roles}
        choices = ([{'entry': template_id(r['npc_id']), 'name': r['name']} for r in roles]
                   if len(names) == 1 else [])
    from .packet_entity_facts import best_position
    result = {}
    for actor in choices:
        for unit in visible_units:
            position = best_position(unit)
            if (template_id(unit.get('entry_id')) == actor['entry'] and position
                    and _local(point, position)):
                result[actor['entry']] = {**actor, 'source': 'QUEST_GIVER_AT_CURRENT_OBJECTIVE'}
    return list(result.values())
