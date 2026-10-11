"""TDB-first search regions; live identity and shared navmesh remain mandatory.

Trinity world X/Y are already WoW world yards (no screen/map scaling or axis
swap). Raw geometry is retained; zeros do not fabricate a known terrain Z.
"""
from __future__ import annotations

import math
import time
from functools import lru_cache
from copy import deepcopy
from .models import number


def _finite(value):
    result = number(value)
    return result if result is not None and math.isfinite(result) else None


def _inside(x, y, vertices):
    inside = False
    previous = vertices[-1]
    for current in vertices:
        ax, ay = previous['x'], previous['y']
        bx, by = current['x'], current['y']
        if (ay > y) != (by > y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
            inside = not inside
        previous = current
    return inside


def geometry_points(points):
    if len(points) > 256:
        return []  # over-budget geometry stays queryable, never stalls a control tick
    key = tuple((_finite(p.get('x')), _finite(p.get('y')), _finite(p.get('z'))) for p in points)
    return deepcopy(_geometry_points(key))


@lru_cache(maxsize=256)
def _geometry_points(key):
    """Bounded interior samples, never interpret polygon vertices as objects.

    Unknown/mixed heights remain unknown; navigation must resolve a floor.
    Degenerate/self-intersecting outlines are not auto-routable.
    """
    points = [dict(zip(('x','y','z'), p)) for p in key]
    if not points or any(p['x'] is None or p['y'] is None for p in points):
        return []
    if len(points) == 1:
        return [dict(points[0])]
    vertices = [{'x':float(p['x']), 'y':float(p['y'])} for p in points]
    if vertices[0] == vertices[-1]:
        vertices.pop()
    if len(vertices) < 3 or len({(p['x'],p['y']) for p in vertices}) != len(vertices):
        return []
    def cross(a,b,c):
        return (b['x']-a['x'])*(c['y']-a['y'])-(b['y']-a['y'])*(c['x']-a['x'])
    edges = list(zip(vertices, vertices[1:]+vertices[:1]))
    for i,(a,b) in enumerate(edges):
        for j,(c,d) in enumerate(edges):
            if j <= i or j-i == 1 or (i==0 and j==len(edges)-1):
                continue
            if cross(a,b,c)*cross(a,b,d) <= 0 and cross(c,d,a)*cross(c,d,b) <= 0:
                return []
    xs,ys = [p['x'] for p in vertices],[p['y'] for p in vertices]
    left,right,top,bottom = min(xs),max(xs),min(ys),max(ys)
    if right-left <= .01 or bottom-top <= .01:
        return []
    # Cell centres stay inside the polygon, not on a ledge boundary.
    samples = [{'x':left+(right-left)*(col+.5)/5, 'y':top+(bottom-top)*(row+.5)/5}
               for row in range(5) for col in range(5)]
    return [p for p in samples if _inside(p['x'],p['y'],vertices)]


def _failed(reference, hint):
    return sum(r.get('kind')=='HINT_OUTCOME' and r.get('hint_id')==hint
               and r.get('outcome')=='FAILURE' and r.get('observed_at',0)>=time.time()-86400
               for r in reference.get('learned') or ()) >= 2


def _destination(state, point, source, hint, **extra):
    player = state.get('player_world_position') or {}
    x,y,z = (_finite(point.get(k)) for k in ('x','y','z'))
    px,py = (_finite(player.get(k)) for k in ('x','y'))
    if (None in (x,y,px,py) or player.get('coordinate_space')!='WORLD_YARDS'
            or player.get('instance_id') is None or state.get('map_id') is None):
        return None
    if math.hypot(x-px,y-py) > 2000:
        return None  # regional navigation only; no invented cross-map travel
    known_z = z is not None and z != 0 and point.get('z_known') is not False
    return {'x':x,'y':y, 'map_id':state['map_id'], 'ui_map_id':state['map_id'],
            'instance_id':player['instance_id'], 'coordinate_space':'WORLD_YARDS',
            **({'z':z,'z_source':'TDB_WORLD','z_confidence':.8} if known_z else {}),
            'z_known':known_z, 'z_observed':False, 'z_estimated':True,
            'source':source, 'reference_hint_id':hint, 'knowledge_priority':'PRIMARY_STATIC',
            'confirmed':False,'navigation_trusted':False,'require_navmesh':True, **extra}


def _poi_regions(state, reference, matches):
    player = state.get('player_world_position') or {}
    result = []
    for poi in reference.get('pois') or ():
        if (not matches(poi) or poi.get('geometry_ambiguous') or poi.get('geometry_mixed_build')
                or poi.get('world_map_id') != player.get('instance_id')
                or poi.get('ui_map_id') != state.get('map_id')
                or any(v not in (None,0) for v in (poi.get('conditions') or {}).values())):
            continue
        hint = 'poi:'+str(poi['poi_id'])
        if _failed(reference,hint):
            continue
        raw_points = poi.get('points') or []
        points = geometry_points(raw_points)
        if not points:
            continue
        # A 2D polygon cannot identify a cave floor. Keep it queryable, but
        # let live markers / explicit spawn Z supply the missing layer.
        if len(raw_points)>1:
            heights = [_finite(p.get('z')) for p in raw_points]
            if any(z in (None,0) for z in heights) or max(heights)-min(heights)>5:
                continue
            for p in points:
                p['z'] = sum(heights)/len(heights)
        px,py = _finite(player.get('x')),_finite(player.get('y'))
        if px is None or py is None:
            continue
        chosen = min(points,key=lambda p:math.hypot(p['x']-px,p['y']-py))
        region = _destination(state,chosen,'TDB_REFERENCE_POI',hint,
            poi_id=poi['poi_id'], verified_build=poi.get('verified_build'),
            point_group_id=poi.get('point_group_id'),
            source_sha256=poi.get('source_sha256'),
            region_source='TDB_POLYGON_CANDIDATE' if len(raw_points)>1 else 'TDB_POINT',
            **({'coverage_points':points, 'polygon_points':raw_points} if len(raw_points)>1 else {}))
        if region:
            result.append(region)
    return result


def _spawn_regions(state, reference, matches, *, allow_unknown_phase=False):
    player = state.get('player_world_position') or {}
    result = []
    for spawn in reference.get('spawn_candidates') or ():
        context = spawn.get('context') or {}
        # An unknown live phase does not make an exact, quest-linked spawn a
        # confirmed object, but it can still be a *search destination*. A
        # known mismatch remains excluded. Other server-only spawn masks
        # cannot be resolved safely from the addon state.
        phase_id = context.get('PhaseId')
        # A spawn seen live (learned row within 15 yd) is in the player's
        # phase by observation; its static phase mask cannot exclude it.
        phase_required = phase_id not in (None, 0, '', '0') and not spawn.get('live_confirmed')
        live_phase = state.get('phase')
        if (not matches(spawn) or spawn.get('world_map_id')!=player.get('instance_id')
                or (phase_required and (live_phase is None and not allow_unknown_phase
                                        or live_phase is not None
                                        and str(phase_id) != str(live_phase)))
                or any(context.get(k) not in (None,0,'', '0') for k in
                       ('PhaseGroup','phaseUseFlags'))
                or context.get('terrainSwapMap') not in (None,0,-1,'','0','-1')
                or context.get('spawnDifficulties') not in (None,'','0')):
            continue
        hint = f"spawn:{spawn.get('entity_kind')}:{spawn.get('spawn_id')}"
        if _failed(reference,hint):
            continue
        region = _destination(state,spawn,spawn.get('source') if spawn.get('source')=='LEARNED_SPAWN' else 'TDB_SPAWN',hint,
            reference_entry=spawn.get('entry'), reference_entity_kind=spawn.get('entity_kind'),
            verified_build=spawn.get('verified_build'),source_sha256=spawn.get('source_sha256'),
            phase_unverified=bool(phase_required and live_phase is None))
        if region:
            result.append(region)
    return result


def _nearest(state, candidates):
    player = state.get('player_world_position') or {}
    px,py = _finite(player.get('x')),_finite(player.get('y'))
    if px is None or py is None or not candidates:
        return None
    pz = _finite(player.get('z')) if player.get('z_known') is not False else None
    def distance(row):
        xy = math.hypot(row['x']-px,row['y']-py)
        z = _finite(row.get('z')) if row.get('z_known') is not False else None
        if pz is not None and z is not None:
            return (0 if abs(z-pz)<=8 else 1, math.hypot(xy,z-pz))
        return (1,xy)
    return min(candidates,key=distance)


def objective_zone_contains_player(state, quest_id, objective_id, *, margin_yards=6.):
    """Whether the player is in a matching TDB POI search zone.

    This is an XY *search gate*, never a movement destination or an entity
    identity. Return None when no unambiguous same-map geometry is available.
    A different cave floor is not treated as the same local search area.
    """
    reference = ((state.get('reference_knowledge') or {}).get('quests') or {}).get(str(quest_id)) or {}
    player = state.get('player_world_position') or {}
    px, py, pz = (_finite(player.get(k)) for k in ('x', 'y', 'z'))
    if px is None or py is None or player.get('instance_id') is None:
        return None
    oid = str(objective_id or '')
    index = oid.split(':', 1)[1] if oid.startswith(str(quest_id)+':') else None
    ids = {str(o.get('objective_id')) for o in reference.get('objectives') or ()
           if str(o.get('objective_id')) == oid
           or index is not None and str(o.get('order')) == index}
    ids.add(oid)
    known = False
    for poi in reference.get('pois') or ():
        if (str(poi.get('objective_id')) not in ids
                and (index is None or str(poi.get('objective_index')) != index)):
            continue
        if (poi.get('geometry_ambiguous') or poi.get('geometry_mixed_build')
                or poi.get('world_map_id') != player.get('instance_id')
                or poi.get('ui_map_id') != state.get('map_id')
                or any(v not in (None, 0) for v in (poi.get('conditions') or {}).values())):
            continue
        points = poi.get('points') or []
        if not geometry_points(points):
            continue
        vertices = [(_finite(p.get('x')), _finite(p.get('y')), _finite(p.get('z')))
                    for p in points]
        if len(vertices) > 1 and vertices[0][:2] == vertices[-1][:2]:
            vertices.pop()
        if not vertices:
            continue
        known = True
        heights = [z for _x, _y, z in vertices if z not in (None, 0)]
        floor_matches = (pz is None or not heights or min(abs(pz-z) for z in heights) <= 15.)
        if len(vertices) == 1:
            horizontal = math.hypot(px-vertices[0][0], py-vertices[0][1])
            if horizontal <= margin_yards and floor_matches:
                return True
            continue
        xy = [{'x': x, 'y': y} for x, y, _z in vertices]
        if _inside(px, py, xy) and floor_matches:
            return True
        if floor_matches:
            for a, b in zip(vertices, vertices[1:]+vertices[:1]):
                vx, vy = b[0]-a[0], b[1]-a[1]
                scale = max(0., min(1., ((px-a[0])*vx+(py-a[1])*vy) / (vx*vx+vy*vy)))
                if math.hypot(px-(a[0]+scale*vx), py-(a[1]+scale*vy)) <= margin_yards:
                    return True
    return False if known else None


def _live_objective_points(state, quest_id, objective):
    """Current client POIs in world yards, never normalized map pixels."""
    from .planning_types import world_point
    sources = [getattr(objective, 'target_location', None)]
    sources.extend(p for p in state.get('quest_locations') or ()
                   if isinstance(p, dict) and str(p.get('quest_id')) == str(quest_id)
                   and str(p.get('role') or '').upper() not in {'TURN_IN', 'QUEST_TURN_IN'})
    result = []
    for source in sources:
        point = world_point(source)
        if (point and point.get('instance_id') ==
                (state.get('player_world_position') or {}).get('instance_id')
                and point.get('map_id') == state.get('map_id')):
            result.append(point)
    return result


def _live_point_matches_poi(point, poi, *, margin_yards=20.):
    vertices = [(_finite(p.get('x')), _finite(p.get('y')))
                for p in poi.get('points') or ()]
    if (not vertices or len(vertices) > 256
            or any(None in vertex for vertex in vertices)):
        return False
    if len(vertices) > 1 and vertices[0] == vertices[-1]:
        vertices.pop()
    px, py = point['x'], point['y']
    if len(vertices) == 1:
        return math.hypot(px-vertices[0][0], py-vertices[0][1]) <= margin_yards
    if not geometry_points(poi.get('points') or []):
        return False
    xy = [{'x': x, 'y': y} for x, y in vertices]
    if _inside(px, py, xy):
        return True
    for a, b in zip(vertices, vertices[1:]+vertices[:1]):
        vx, vy = b[0]-a[0], b[1]-a[1]
        t = max(0., min(1., ((px-a[0])*vx+(py-a[1])*vy)/(vx*vx+vy*vy)))
        if math.hypot(px-(a[0]+t*vx), py-(a[1]+t*vy)) <= margin_yards:
            return True
    return False


def objective_region(state, quest_id, objective):
    # Static POIs describe all possible sites, including already completed
    # stages. Live quest progress is the authority for whether this objective
    # may still supply a destination at all.
    if getattr(objective, 'completion_state', None) == 'COMPLETE':
        return None
    reference = ((state.get('reference_knowledge') or {}).get('quests') or {}).get(str(quest_id)) or {}
    if not reference or getattr(objective,'objective_id',None) is None:
        return None
    oid = str(objective.objective_id)
    index = oid.split(':',1)[1] if oid.startswith(str(quest_id)+':') else None
    matched = [o for o in reference.get('objectives') or () if str(o.get('objective_id'))==oid
               or index is not None and str(o.get('order'))==index]
    ids = {str(o['objective_id']) for o in matched} | {oid}
    def poi_for_objective(p):
        return (str(p.get('objective_id')) in ids
                or not matched and index is not None
                and str(p.get('objective_index')) == index)
    live_points = _live_objective_points(state, quest_id, objective)
    matching_pois = [p for p in reference.get('pois') or ()
                     if poi_for_objective(p) and not p.get('geometry_ambiguous')
                     and not p.get('geometry_mixed_build')
                     and p.get('world_map_id') == (state.get('player_world_position') or {}).get('instance_id')
                     and p.get('ui_map_id') == state.get('map_id')
                     and not any(v not in (None, 0) for v in (p.get('conditions') or {}).values())]
    # A current client POI contradicting every matching TDB POI wins. Static
    # data can refine the live location, never silently override it.
    agreed_pois = [p for p in matching_pois
                   if not live_points or any(_live_point_matches_poi(point, p)
                                             for point in live_points)]
    if live_points and matching_pois and not agreed_pois:
        return None
    live = next((q for q in state.get('active_quests') or () if str(q.get('quest_id'))==str(quest_id)), {})
    live_objectives = live.get('objectives') or ()
    current = next((o for i,o in enumerate(live_objectives) if str(o.get('objective_id',f'{quest_id}:{i}'))==oid), {})
    if current.get('is_complete') is True:
        return None
    count = _finite(current.get('current',current.get('current_count')))
    consumed = [r.get('position') or {} for r in reference.get('learned') or ()
                if r.get('kind')=='OBJECTIVE_REGION' and str(r.get('objective_id'))==oid
                and r.get('skill')=='OBJECT_USE' and count is not None
                and 0 < (_finite(r.get('after')) or 0) <= count]
    # A verified correction in this character/map/phase scope precedes static data.
    for row in reference.get('learned') or ():
        if row.get('kind')!='OBJECTIVE_REGION' or str(row.get('objective_id'))!=oid:
            continue
        point = row.get('position') or {}
        if point in consumed:
            continue  # already freed/collected here; progress is not a reason to return
        if point.get('instance_id') != (state.get('player_world_position') or {}).get('instance_id'):
            continue
        hint = 'learned:'+oid+':'+':'.join(str(round(point[k])) for k in ('x','y','z') if _finite(point.get(k)) is not None)
        if not _failed(reference,hint):
            result = _destination(state,point,'LEARNED_OBJECTIVE_REGION',hint)
            if result:
                return result
    candidates = _poi_regions(state,reference,
                              lambda p: poi_for_objective(p) and p in agreed_pois)
    if not candidates:
        def matching_spawn(s):
            if s.get('role') not in {'OBJECTIVE', 'ITEM_SOURCE'} or str(s.get('objective_id')) not in ids:
                return False
            if live_points and agreed_pois:
                # Do not jump from a matching quest zone to an unrelated
                # phase/spawn of the same GO entry elsewhere on this map.
                return any(_live_point_matches_poi(s, p, margin_yards=6.)
                           for p in agreed_pois)
            if live_points:
                return any(math.hypot(s['x']-p['x'], s['y']-p['y']) <= 25.
                           for p in live_points)
            return True
        candidates = _spawn_regions(state,reference,matching_spawn,
                                    allow_unknown_phase=bool(live_points and agreed_pois))
    candidates = [p for p in candidates if not any(
        all(_finite(c.get(k)) is not None for k in ('x','y','z'))
        and _finite(p.get('z')) is not None and abs(p['z']-c['z']) <= 5
        and math.hypot(p['x']-c['x'],p['y']-c['y']) <= 10 for c in consumed)]
    exact_spawns = (len(candidates) > 1 and all(
        p.get('source') in {'TDB_SPAWN', 'LEARNED_SPAWN'} for p in candidates))
    if exact_spawns and any(
            isinstance(v, dict) and v.get('kind') == 'minimap_quest_dot'
            for v in state.get('visual_candidates') or ()):
        # The live dot identifies which of several precise static locations
        # is currently relevant. Static geometry refines it, not vice versa.
        from .quest_location_planning import minimap_objective_dots
        dots = [(x, y) for x, y, qid in minimap_objective_dots(state)
                if str(qid) == str(quest_id)]
        corroborated = [(min(math.hypot(p['x']-x, p['y']-y) for x, y in dots), p)
                        for p in candidates] if dots else []
        corroborated = [(distance, p) for distance, p in corroborated if distance <= 12.]
        if corroborated:
            best_distance = min(distance for distance, _p in corroborated)
            candidates = [p for distance, p in corroborated
                          if distance <= best_distance + 3.]
            for p in candidates:
                p['objective_dot_correlated'] = True
        elif count is not None and count > 0:
            # A multi-use objective's current counter does not identify
            # which static spawns are already spent.  The minimap shows a dot
            # for every remaining one within its view: a spawn inside the
            # view (not under the player arrow) without a dot is used or
            # absent; one beyond the view is still a fair place to go (user
            # 2026-10-10: dots first, else the objective spawns, else sweep).
            view = next((_finite(v.get('view_radius_yards')) for v in state.get('visual_candidates') or ()
                         if isinstance(v, dict) and v.get('kind') == 'minimap_quest_dot'), None)
            player = state.get('player_world_position') or {}
            px, py = _finite(player.get('x')), _finite(player.get('y'))
            if view is None or px is None or py is None:
                return None
            candidates = [p for p in candidates
                          if math.hypot(p['x']-px, p['y']-py) >= .9*view]
            if not candidates:
                return None
    elif exact_spawns and count is not None and count > 0:
        return None
    return _nearest(state,candidates)


def _role_spawn_height(reference, role, npc_id, point, radius=20.):
    """Height of the same role's static spawn next to a height-less point."""
    x, y = _finite(point.get('x')), _finite(point.get('y'))
    if x is None or y is None:
        return None
    best = None
    for spawn in reference.get('spawn_candidates') or ():
        z = _finite(spawn.get('z'))
        if (spawn.get('role') != role or z in (None, 0)
                or (npc_id is not None and spawn.get('entry') not in (None, npc_id)
                    and str(spawn.get('entry')) != str(npc_id))
                or _finite(spawn.get('x')) is None or _finite(spawn.get('y')) is None):
            continue
        distance = math.hypot(spawn['x']-x, spawn['y']-y)
        if distance <= radius and (best is None or distance < best[0]):
            best = (distance, z)
    return None if best is None else best[1]


def role_region(state, quest_id, role, *, live_location=None):
    reference = ((state.get('reference_knowledge') or {}).get('quests') or {}).get(str(quest_id)) or {}
    from .planning_types import world_point
    live = world_point(live_location)
    if live and (live.get('instance_id') != (state.get('player_world_position') or {}).get('instance_id')
                 or live.get('map_id') != state.get('map_id')):
        live = None
    def agrees(candidate):
        return (live is None or math.hypot(candidate['x']-live['x'], candidate['y']-live['y']) <= 35.)
    for row in reference.get('learned') or ():
        if row.get('kind')!='QUEST_ROLE' or row.get('role')!=role or not row.get('confirmed_historical'):
            continue
        point = row.get('observer_position') or {}
        if point.get('instance_id') != (state.get('player_world_position') or {}).get('instance_id'):
            continue
        if _finite(point.get('z')) in (None, 0):
            # Live 2026-10-11 15:56: the learned spot of Bjorn (55965 ender)
            # had no height; at the pit entrance the route chose the cave
            # floor below.  The same NPC's TDB spawn beside it knows the floor.
            z = _role_spawn_height(reference, role, row.get('npc_id'), point)
            if z is not None:
                point = {**point, 'z': z, 'z_known': True}
        hint = f"learned-role:{quest_id}:{role}:{row.get('npc_id')}"
        if not _failed(reference,hint):
            known = _destination(state,point,'LEARNED_QUEST_ROLE_REGION',hint,
                                 location_kind='OBSERVER_SEARCH_REGION')
            if known and agrees(known):
                return known
    if role=='QUEST_ENDER' and reference.get('turnin_status')=='AMBIGUOUS_TEXT_ROLE_CONFLICT':
        return None
    # The typed relation is stronger than an arbitrary quest waypoint. Static
    # presence does NOT prove this quest is available or this NPC is visible.
    candidates = _spawn_regions(state,reference,lambda s: s.get('role')==role,
                                allow_unknown_phase=live is not None)
    if not candidates and role=='QUEST_ENDER':
        candidates = _poi_regions(state,reference,lambda p: p.get('objective_index')==-1)
    candidates = [candidate for candidate in candidates if agrees(candidate)]
    return _nearest(state,candidates)
