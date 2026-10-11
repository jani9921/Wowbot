"""Quest-zone sweep (user 2026-10-10): walk the TDB quest-POI area in a
serpentine of 25 yd cells, at once when nothing is at hand; only something
quest relevant interrupts it."""
import math

from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.visual_search_planning import VisualSearchPlanningPolicy as Policy
from wowbot.agent.world import WorldModel
from wowbot.navigation.search_coverage import SearchCoveragePlanner

# Murloc Mania (55122) objective 0, real TDB quest_poi_points.
MURLOC_POLYGON = [{"x": x, "y": y, "z": z} for x, y, z in (
    (-382, -2620, 9), (-354, -2609, 8), (-311, -2589, 19), (-318, -2484, 14),
    (-396, -2489, 13), (-400, -2521, 15), (-401, -2604, 7))]


def _state(quest_id, objective, *, player=(-370., -2560.), boxes=()):
    return {"session_id": "s", "frame_id": "f", "timestamp": 1, "monotonic_time": 1,
            "map_id": 1409, "player_present": True,
            "active_quests": [{"quest_id": quest_id, "is_complete": False, "objectives": [objective]}],
            "player_world_position": {"coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                                      "ui_map_id": 1409, "x": player[0], "y": player[1]},
            "quest_locations": [{"quest_id": quest_id, "map_id": 1409, "x": .6, "y": .8,
                                 "world_position": {"coordinate_space": "WORLD_YARDS",
                                                    "instance_id": 2175, "ui_map_id": 1409,
                                                    "x": -360., "y": -2550.}}],
            "reference_knowledge": {"quests": {str(quest_id): {"pois": [
                {"poi_id": f"{quest_id}:0:1", "objective_index": 0, "world_map_id": 2175,
                 "ui_map_id": 1409, "points": MURLOC_POLYGON, "conditions": {}}],
                "spawn_candidates": [{"role": "ITEM_SOURCE", "world_map_id": 2175,
                                      "x": -367., "y": -2541.}]}}},
            "visual_candidates": list(boxes)}


def _world(state):
    world = WorldModel()
    world.ingest(Observation.create(state, 1))
    return world


UNIT = {"source": "WORLD3D", "track_id": "WORLD3D:1", "kind": "unknown_subject_candidate",
        "candidate_labels": ["learned_subject_like"],
        "appearance": {"learned_label_hypothesis": "creature_unit_like"}}
OBJECT = {"source": "WORLD3D", "track_id": "WORLD3D:2", "kind": "unknown_object_candidate",
          "candidate_labels": ["learned_object_like", "quest_object_like"],
          "appearance": {"learned_label_hypothesis": "quest_object_outline_like"}}
SPIN = Proposal.make("SEEK_VISUAL_CUE", "spin", {"source": "WORLD3D", "kind": "active_visual_search",
                     "purpose": "FIND_LOCAL_QUEST_RELEVANT_SUBJECT", "spin_search": True}, priority=78)


def _identify(box):
    return Proposal.make("SEEK_VISUAL_CUE", "far track", {**box, "purpose": "IDENTIFY"}, priority=78)


def _inspect(box):
    return Proposal.make("INSPECT", "hover", {"source": "WORLD3D", "track_id": box["track_id"]},
                         priority=85)


def test_cells_are_a_serpentine_inside_the_polygon_and_spawn_weighted():
    cells = Policy.sweep_cells(MURLOC_POLYGON, [(-367., -2541.)])
    from wowbot.agent.tdb_locations import _inside
    assert 8 <= len(cells) <= 64
    assert all(_inside(c["x"], c["y"], MURLOC_POLYGON) for c in cells)
    steps = [math.hypot(a["x"]-b["x"], a["y"]-b["y"]) for a, b in zip(cells, cells[1:])]
    assert sum(step <= 35. for step in steps) >= .8*len(steps)       # neighbour to neighbour
    assert any(c.get("weight") for c in cells)
    assert all("z" not in c for c in cells)        # a 7..19 yd deep polygon: own floor


def test_a_visited_cell_needs_10_yards_and_weight_only_breaks_ties():
    planner = SearchCoveragePlanner()
    planner.begin("zone", {"x": 0., "y": 0., "radius": 60., "visit_radius": 10.,
                           "coverage_points": [{"x": 0., "y": 30.}, {"x": 0., "y": 35., "weight": 3.},
                                               {"x": 0., "y": 120., "weight": 3.}]})
    first = planner.next_waypoint("zone", player_x=0., player_y=0.)
    assert (first["x"], first["y"]) == (0., 35.)        # 5 yd farther but a spawn nearby
    planner.observe("zone", player_x=0., player_y=22., target_detected=False, now=1.)
    assert not planner.completed("zone")                 # 13/8 yd away: not yet visited


def test_cocoon_like_object_quest_keeps_only_object_cues_then_sweeps():
    objective = {"objective_id": "55639:0", "type": "USE_OBJECT", "raw_type": "object",
                 "description": "0/5 Trapped Expedition Member rescued from cocoons",
                 "current": 0, "required": 5}
    state = _state(55639, objective, boxes=(UNIT, OBJECT))
    world = _world(state)
    kept = Policy().zone_sweep_mode(world, Goal.parse("Questelj", 1), world.state,
                                    [SPIN, _identify(UNIT), _identify(OBJECT), _inspect(UNIT)],
                                    None, busy=False)
    assert [p.parameters.get("track_id") for p in kept] == ["WORLD3D:2"]
    nothing = Policy().zone_sweep_mode(world, Goal.parse("Questelj", 1), world.state,
                                       [SPIN, _identify(UNIT), _inspect(UNIT)], None, busy=False)
    assert [p.skill for p in nothing] == ["SEEK_VISUAL_CUE"]
    sweep = nothing[0].parameters
    assert sweep["roam_quest_area"] and sweep["search_area"]["region_source"] == "TDB_QUEST_POI_POLYGON"
    assert nothing[0].priority == Policy.ZONE_SWEEP_PRIORITY


def test_a_kill_quest_still_looks_at_units_and_outside_the_zone_nothing_changes():
    objective = {"objective_id": "55122:0", "type": "COLLECT", "raw_type": "item",
                 "description": "0/6 First Aid Kits recovered from defeated Murlocs",
                 "current": 0, "required": 6}
    world = _world(_state(55122, objective, boxes=(UNIT,)))
    kept = Policy().zone_sweep_mode(world, Goal.parse("Questelj", 1), world.state,
                                    [SPIN, _identify(UNIT)], None, busy=False)
    assert [p.parameters.get("purpose") for p in kept] == ["IDENTIFY"]
    busy = Policy().zone_sweep_mode(world, Goal.parse("Questelj", 1), world.state, [SPIN], None,
                                    busy=True)
    assert busy == [SPIN]
    away = _world(_state(55122, objective, player=(-700., -2560.), boxes=(UNIT,)))
    assert Policy().zone_sweep_mode(away, Goal.parse("Questelj", 1), away.state,
                                    [SPIN], None, busy=False) == [SPIN]


def test_the_sweep_keeps_walking_and_glances_left_and_right(tmp_path):
    """User 2026-10-10: continuous walk with a sweeping camera.  CAMERA_GLANCE
    is a left-button drag that keeps the forward lease (W stays down)."""
    from types import SimpleNamespace
    from wowbot.agent.active_skill_supervision import ActiveSkillSupervisor
    from wowbot.agent.bindings import BindingsCache
    from wowbot.agent.executor import InputExecutor
    from wowbot.agent.models import Command
    from test_input_scheduler import Backend

    supervisor = ActiveSkillSupervisor.__new__(ActiveSkillSupervisor)
    walk = (Command("BIND", "MOVEFORWARD", .08),)
    attempt = SimpleNamespace(action_id="a1", proposal=Proposal.make(
        "MOVE", "sweep", {"purpose": "SEARCH_LOCAL_OBJECTIVE_AREA", "scan_while_moving": True}))
    assert supervisor._sweep_glance(attempt, walk, 0.) == ()
    assert supervisor._sweep_glance(attempt, walk, 1.) == ()
    left = supervisor._sweep_glance(attempt, walk, 2.6)
    right = supervisor._sweep_glance(attempt, walk, 5.2)
    assert [c.kind for c in left + right] == ["CAMERA_GLANCE", "CAMERA_GLANCE"]
    assert left[0].x < .5 < right[0].x
    assert supervisor._sweep_glance(attempt, (), 9.) == ()          # standing: no glance
    plain = SimpleNamespace(action_id="a2", proposal=Proposal.make("MOVE", "route", {}))
    assert supervisor._sweep_glance(plain, walk, 20.) == ()

    cache_path = tmp_path / "bindings-cache.wtf"
    cache_path.write_text('bind "W" "MOVEFORWARD"\n', encoding="utf-8")
    backend = Backend()
    executor = InputExecutor(42, BindingsCache(cache_path), backend)
    try:
        executor.execute_movement((Command("BIND", "MOVEFORWARD", .08),))
        executor.execute(left)
        assert ("BUTTON1", True) in backend.calls and ("BUTTON1", False) in backend.calls
        assert ("W", False) not in backend.calls and backend.down["W"] is True
    finally:
        executor.close()


def test_remembered_dots_survive_a_turned_camera_and_vanished_ones_are_dropped():
    from wowbot.agent.quest_dot_focus import QuestDotFocus
    state = {"session_id": "s", "map_id": 1409,
             "player_world_position": {"instance_id": 2175, "x": 0., "y": 0.},
             "active_quests": [{"quest_id": 55639, "objectives": [
                 {"objective_id": "55639:0", "current": 1, "required": 5}]}]}
    focus = QuestDotFocus()
    first = focus.select(state, [(10., 0., "55639"), (0., 30., "55639")], x=0., y=0., now=0.,
                         view_radius=60.)
    assert (first.x, first.y) == (10., 0.)
    focus.arrived(1.)
    focus.select(state, [], x=10., y=0., now=40., view_radius=None)   # local search over, retired
    nxt = focus.select(state, [], x=10., y=0., now=41., view_radius=None)
    assert nxt is not None and (round(nxt.x), round(nxt.y)) == (0, 30)   # camera turned: remembered
    # Seen again inside the view, 30 yd away and not under the arrow: no dot
    # any more there means the cocoon is gone.
    gone = QuestDotFocus()
    gone.select(state, [(0., 30., "55639")], x=0., y=0., now=0., view_radius=60.)
    gone.focus = None
    assert gone.select(state, [], x=0., y=0., now=5., view_radius=60.) is None


def test_spawns_inside_the_minimap_without_a_dot_are_skipped_far_ones_remain():
    from types import SimpleNamespace
    from wowbot.agent.tdb_locations import objective_region
    spawn = {"role": "OBJECTIVE", "entity_kind": "GAMEOBJECT", "objective_id": 391020,
             "world_map_id": 2175, "context": {}}
    state = {"map_id": 1409,
             "player_world_position": {"coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                                       "x": 0., "y": 0.},
             "active_quests": [{"quest_id": 55639, "objectives": [
                 {"objective_id": "55639:0", "current": 2, "required": 5}]}],
             "visual_candidates": [{"kind": "minimap_quest_dot", "view_radius_yards": 40., "dots": []}],
             "reference_knowledge": {"quests": {"55639": {
                 "objectives": [{"objective_id": 391020, "order": 0, "raw_type": 2}],
                 "pois": [], "learned": [],
                 "spawn_candidates": [{**spawn, "spawn_id": 1, "x": 20., "y": 0., "z": 50.},
                                      {**spawn, "spawn_id": 2, "x": 60., "y": 0., "z": 50.}]}}}}
    region = objective_region(state, 55639, SimpleNamespace(objective_id="55639:0",
                                                            completion_state=None))
    assert region is not None and region["x"] == 60.


def test_inside_the_zone_a_plain_area_move_does_not_block_the_sweep():
    """Live 2026-10-11 13:36 (Cooking Meat, inside the POI polygon): the only
    other proposal, a MOVE to the API area point, was later blocked by a fall
    hazard; zone mode had counted it as work at hand and the agent waited."""
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    objective = {"objective_id": "55174:0", "type": "COLLECT", "raw_type": "item",
                 "description": "1/5 Raw Meat collected from wildlife", "current": 1, "required": 5}
    state = _state(55174, objective)
    state["quest_locations"][0]["world_position"].update(x=-330., y=-2500.)   # 40 yd away
    world = _world(state)
    proposals = sorted(Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world, 1),
                       key=lambda item: -item.priority)
    assert proposals[0].skill == "SEEK_VISUAL_CUE" and proposals[0].parameters.get("zone_sweep")
