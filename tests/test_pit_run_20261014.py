"""Live 2026-10-14 13:32-13:36 (Who Lurks in the Pit, Hrun's pit)."""
import math
from types import SimpleNamespace

from wowbot.query_ports import NavigationQueryPorts

from wowbot.navigation import NavigationService
from wowbot.navigation.contracts import GlobalRoute
from wowbot.navigation.z_resolver import ResolvedPosition

# Hrun's pit cocoons (GAMEOBJECT 339568), top to bottom.
COCOONS = ((8000022, 80.48, -2279.52, 60.42), (8000025, 111.06, -2217.92, 32.95),
           (8000023, 36.03, -2199.45, 17.01), (8000026, 65.34, -2276.59, -.66),
           (8000024, 123.57, -2238.92, -5.86))


def _quest(current=0):
    return {"quest_id": 55639, "is_complete": False, "objectives": [
        {"objective_id": "55639:0", "description": "Trapped Expedition Member rescued from cocoons",
         "type": "INTERACT", "raw_type": "object", "current": current, "required": 5,
         "is_complete": False}]}


def _reference(cocoons=COCOONS):
    return {"quests": {"55639": {"spawn_candidates": [
        {"spawn_id": sid, "entry": 339568, "entity_kind": "GAMEOBJECT", "role": "OBJECTIVE",
         "objective_id": "55639:0", "world_map_id": 2175, "x": x, "y": y, "z": z,
         "source": "TDB_REFERENCE"} for sid, x, y, z in cocoons]}}}


def _state(x=93.1, y=-2249.5, **extra):
    return {"monotonic_time": 10., "map_id": 1409, "session_id": "s",
            "player_world_position": {"x": x, "y": y, "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS", "z_known": False},
            "active_quests": [_quest()], "reference_knowledge": _reference(), **extra}


# --- 1a: the TDB spawn choice uses the navmesh floor of the player ----------------

def test_the_player_floor_from_the_navmesh_picks_the_top_cocoon_first():
    """13:33:20: no player Z from Retail -> 2D distance -> the pit bottom
    (z -5.9, 32.3 yd) won over the top cocoon (z 60, 32.6 yd)."""
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    from wowbot.agent.tdb_locations import _nearest
    rows = [{"x": x, "y": y, "z": z, "hint": sid} for sid, x, y, z in COCOONS]
    state = _state()
    assert _nearest(state, rows)["hint"] == 8000024
    world = SimpleNamespace(state=state)
    layered = QuestLocationPlanningPolicy.with_player_layer(world, state,
        navigation_queries=NavigationQueryPorts(player_layer=lambda _state: 95.3))
    assert layered["player_world_position"]["z"] == 95.3
    assert state["player_world_position"].get("z") is None          # no mutation
    assert _nearest(layered, rows)["hint"] == 8000022


def test_navigation_reports_the_resolved_player_floor():
    nav = NavigationService()
    state = _state()
    assert nav.player_layer_z(state) is None
    nav._z.player = ResolvedPosition(93.1, -2249.5, 95.28, .85, "MMAP", 2175, at=9.)
    assert nav.player_layer_z(state) == 95.28
    nav._z.player = ResolvedPosition(93.1, -2249.5, 95.28, .3, "MMAP", 2175, at=9.)
    assert nav.player_layer_z(state) is None


# --- 1b: a multi-floor spawn set is the floor walk's -------------------------------

def test_a_multi_floor_spawn_set_is_recognised_and_a_flat_one_is_not():
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    policy = QuestLocationPlanningPolicy
    assert len(policy.multi_level_spawns(_state(), 55639)) == 5
    flat = _state(reference_knowledge=_reference(tuple((sid, x, y, 10.+k) for k, (sid, x, y, _z)
                                                        in enumerate(COCOONS))))
    assert policy.multi_level_spawns(flat, 55639) == []


def _objective_proposals(state, layer=None):
    from wowbot.agent.models import Observation
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    from wowbot.agent.world import WorldModel
    world = WorldModel()
    world.ingest(Observation.create({**state, "timestamp": 10., "frame_id": 1}, 10.))
    record = world.quest_model.records[55639]
    queries = NavigationQueryPorts(player_layer=(lambda _state: layer) if layer is not None else None)
    return QuestLocationPlanningPolicy(navigation_queries=queries).propose_objective(
        world, record.objectives[0], record, "55639")


def test_no_separate_tdb_spawn_move_for_a_multi_floor_spawn_set():
    """13:33:20-13:34:26: the spawn MOVE (p100) went for the pit bottom, walked
    past the top cocoon and outranked the dots."""
    assert _objective_proposals(_state(), layer=95.3) == []


def test_a_flat_spawn_set_keeps_the_tdb_spawn_move():
    flat = _state(reference_knowledge=_reference(tuple((sid, x, y, 10.+k) for k, (sid, x, y, _z)
                                                        in enumerate(COCOONS))))
    proposals = _objective_proposals(flat)
    assert [p.skill for p in proposals] == ["MOVE"]
    assert proposals[0].parameters["knowledge_priority"] == "PRIMARY_STATIC"


# --- 2: inside the multi-floor zone, no walk back up to the rim POI ----------------

def test_down_in_the_pit_near_a_cocoon_the_zone_is_entered():
    """13:34:32: 27 yd from the rim POI after the first cocoon, "outside the
    area" sent the agent back up to the POI."""
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    policy = QuestLocationPlanningPolicy()
    poi = {"x": 81., "y": -2242., "instance_id": 2175}
    assert policy._within_objective_area(poi, _state(x=77.1, y=-2269.6), 55639)
    # Without the multi-floor spawn set the old 20 yd rule stands.
    assert not policy._within_objective_area(poi, _state(x=77.1, y=-2269.6, reference_knowledge={}), 55639)


def test_a_downward_arrow_of_a_multi_floor_spawn_set_is_left_to_the_floor_walk():
    """13:35:02: from the rim the arrowed dot nearest in 2D sent the agent
    to the pit bottom, past the spiral's cocoons."""
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    import wowbot.agent.quest_location_planning as module
    policy = QuestLocationPlanningPolicy()
    original = module.minimap_vertical_objective_cues
    module.minimap_vertical_objective_cues = lambda _state: [(64.4, -2275.2, "55639", "BELOW", 1.)]
    try:
        state = _state(x=91.9, y=-2229.1)
        assert policy.minimap_vertical_move(SimpleNamespace(state=state)) is None
        assert policy.minimap_vertical_move(SimpleNamespace(state={**state, "monotonic_time": 11.})) is None
        flat = _state(x=91.9, y=-2229.1, reference_knowledge={})
        policy = QuestLocationPlanningPolicy()
        policy.minimap_vertical_move(SimpleNamespace(state=flat))
        module.minimap_vertical_objective_cues = lambda _state: [(64.4, -2275.2, "55639", "BELOW", 2.)]
        move = policy.minimap_vertical_move(SimpleNamespace(state={**flat, "monotonic_time": 11.}))
        assert move is not None and move.parameters["floor_hint"] == "BELOW"
    finally:
        module.minimap_vertical_objective_cues = original


# --- 3: no route spikes from the drop offset ---------------------------------------

class _Walkway:
    """A walkway at z 25 for y >= 0 (and inside a bend), the pit for y < -10."""

    def walkable_heights_at(self, instance_id, point, radius=2.5):
        return [25.] if point["y"] >= -10 else [-19.]


def test_a_drop_offset_that_reverses_the_route_goes_back_to_the_navmesh_corner():
    """13:35:56-13:36:25: one corner shifted 6 yd back against the travel
    direction; the route went 70,-2240 -> 73.6,-2235 -> 70.9,-2241."""
    nav = NavigationService(navmesh=_Walkway())
    anchors = [{"x": 0., "y": 0., "z": 25.}, {"x": 4., "y": 0., "z": 25.},
               {"x": 4., "y": 8., "z": 25., "drop_offset": True, "drop_original": {"x": 4., "y": .5, "z": 25.}},
               {"x": 5., "y": .2, "z": 25.}, {"x": 10., "y": 0., "z": 25.}]
    result = nav._without_drop_spikes(anchors)
    assert [(a["x"], a["y"]) for a in result] == [(0., 0.), (4., 0.), (4., .5), (5., .2), (10., 0.)]
    assert all("drop_original" not in a for a in result)
    # A gentle sideways shift stays.
    gentle = [{"x": 0., "y": 0., "z": 25.},
              {"x": 5., "y": 2., "z": 25., "drop_offset": True, "drop_original": {"x": 5., "y": 0., "z": 25.}},
              {"x": 10., "y": 0., "z": 25.}]
    assert nav._without_drop_spikes(gentle)[1]["y"] == 2.


def test_the_live_route_spike_is_gone_but_the_drop_offset_still_applies():
    class Ledge:
        def walkable_heights_at(self, instance_id, point, radius=2.5):
            return [25.] if point["y"] >= 0 else [-19.]
    nav = NavigationService(navmesh=Ledge())
    nav._z.player = ResolvedPosition(0., 1., 25., .9, "MMAP", 2175, at=1.)
    anchors = tuple({"x": float(x), "y": 1., "z": 25., "instance_id": 2175} for x in range(0, 41, 10))
    route = nav._away_from_drops(GlobalRoute("r", anchors, (), 1., 1., 0., 1.))
    assert all(anchor.get("drop_offset") and anchor["y"] > 5. for anchor in route.anchors[1:-1])
    assert all("drop_original" not in anchor for anchor in route.anchors)


# --- 4: a near intermediate waypoint that stops getting closer is passed -----------

class _Floor:
    def walkable_heights_at(self, instance_id, point, radius=2.5):
        return [73.]


def _route_nav(geometry=None):
    nav = NavigationService(navmesh=geometry or _Floor())
    nav._active_route = GlobalRoute("r", (
        {"x": 65.2, "y": -2230.0, "z": 73.2, "instance_id": 2175},
        {"x": 65.7, "y": -2237.2, "z": 72.5, "instance_id": 2175},
        {"x": 70.1, "y": -2240.3, "z": 72.8, "instance_id": 2175}), (), 1., 1., 0., 1.)
    nav._route_waypoint_index = 0
    nav._z.player = ResolvedPosition(66.8, -2230.5, 73.0, .9, "MMAP", 2175, at=1.)
    return nav


def _at(x, y):
    return {"player_world_position": {"x": x, "y": y, "instance_id": 2175}}


def test_a_corner_1_6_yd_away_without_progress_is_passed_after_two_seconds():
    """13:35:16-13:35:56: 1.6-1.7 yd from the corner for 40 s (pass radius
    1.5 yd, wall check off near a destination, jitter reset no-progress)."""
    nav = _route_nav()
    jitter = ((66.8, -2230.5), (66.9, -2230.1), (66.7, -2230.8), (66.8, -2230.3))
    assert not any(nav._intermediate_waypoint_stalled(_at(*xy), 1.+.5*k) for k, xy in enumerate(jitter))
    assert nav._intermediate_waypoint_stalled(_at(66.8, -2230.5), 3.1)


def test_getting_closer_restarts_the_stall_clock_and_far_corners_are_not_passed():
    nav = _route_nav()
    assert not nav._intermediate_waypoint_stalled(_at(68.5, -2230.5), 1.)
    assert not nav._intermediate_waypoint_stalled(_at(67.5, -2230.5), 2.)     # 1 yd closer
    assert not nav._intermediate_waypoint_stalled(_at(67.5, -2230.5), 3.5)
    assert nav._intermediate_waypoint_stalled(_at(67.5, -2230.5), 4.1)
    far = _route_nav()
    assert not far._intermediate_waypoint_stalled(_at(72., -2230.), 1.)
    assert not far._intermediate_waypoint_stalled(_at(72., -2230.), 9.)        # 6.8 yd away


class _GapToTheNextCorner:
    """The floor ends 1 yd south of the corner: the next leg crosses a drop."""

    def walkable_heights_at(self, instance_id, point, radius=2.5):
        return [73.] if point["y"] >= -2232. else [10.]


def test_no_stall_pass_when_the_next_leg_crosses_a_drop():
    nav = _route_nav(_GapToTheNextCorner())
    assert not nav._intermediate_waypoint_stalled(_at(66.8, -2230.5), 1.)
    assert not nav._intermediate_waypoint_stalled(_at(66.8, -2230.5), 5.)


def test_the_final_waypoint_is_never_stall_passed():
    nav = _route_nav()
    nav._route_waypoint_index = 2
    assert not nav._intermediate_waypoint_stalled(_at(71.5, -2240.3), 1.)
    assert not nav._intermediate_waypoint_stalled(_at(71.5, -2240.3), 5.)


# --- 14:03-14:08: cocoons clicked from 7.4 / 16 yd ---------------------------------

def _pit_world(x, y, **extra):
    from wowbot.agent.models import Observation
    from wowbot.agent.world import WorldModel
    world = WorldModel()
    world.ingest(Observation.create({**_state(x=x, y=y), "timestamp": 10., "frame_id": 1, **extra}, 10.))
    return world


def test_a_cocoon_on_our_floor_out_of_use_range_is_walked_to_before_any_click():
    """14:03:22 / 14:07:02: right-clicks from 7.4 and 16 yd (the big cocoon
    box looked near), no credit, then out_of_range, a minute on one spot."""
    from wowbot.agent.models import Goal
    from wowbot.agent.planner import Planner
    from wowbot.agent.skills import SkillRegistry
    planner = Planner(SkillRegistry(), navigation_queries=NavigationQueryPorts(
        player_layer=lambda _state: 62.7))  # no movement bindings: read the quest domain
    world = _pit_world(81.8, -2272.2)
    candidates = planner.quest.propose(world, Goal.parse("Questelj", 10.))
    move = next(p for p in candidates if p.parameters.get("purpose") == "APPROACH_QUEST_OBJECT_SPAWN")
    assert (move.parameters["x"], move.parameters["y"]) == (80.48, -2279.52)
    assert move.parameters["stop_distance"] == 2.5 and move.parameters["require_navmesh"]
    assert not any(p.skill == "OBJECT_USE" for p in candidates)
    # At the cocoon: no approach, the hover/use flow takes over.
    near = _pit_world(81.5, -2277.5)
    candidates = planner.quest.propose(near, Goal.parse("Questelj", 10.))
    assert not any(p.parameters.get("purpose") == "APPROACH_QUEST_OBJECT_SPAWN" for p in candidates)


def test_the_spot_is_the_nearest_unspent_spawn_on_our_floor():
    from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
    flow = ObjectInteractionFlow()
    state = _state(x=81.8, y=-2272.2)
    spot = flow.tdb_use_spot(state, 55639, 62.7)
    assert spot["hint"] == "spawn:GAMEOBJECT:8000022" and abs(spot["distance"]-7.4) < .1
    # Unknown floor or another floor: no spot (the cocoon 60 yd below is no target).
    assert flow.tdb_use_spot(state, 55639, None) is None
    assert flow.tdb_use_spot(_state(x=72.1, y=-2265.7), 55639, 95.) is None
    # Credited here: spent for this quest acceptance ...
    flow.note_result({"action_id": "a", "skill": "OBJECT_USE", "outcome": "SUCCESS"},
                     _state(x=81.5, y=-2277.5))
    assert flow.tdb_use_spot(state, 55639, 62.7) is None
    assert flow.object_at_hand(state, 55639, 62.7) is False
    # ... but counts anew once the quest was taken again (progress dropped).
    retaken = _state(x=81.8, y=-2272.2)
    flow.__dict__["_spent_spot_log"] = [(81.5, -2277.5, 10., {"55639": 1.})]
    assert flow.tdb_use_spot(retaken, 55639, 62.7) is not None


def test_a_spot_stood_at_without_credit_is_searched_out():
    from wowbot.agent.object_interaction_flow import ObjectInteractionFlow
    flow = ObjectInteractionFlow()
    at_spot = _state(x=81.5, y=-2277.5)
    assert flow.tdb_use_spot(at_spot, 55639, 62.7)["hint"] == "spawn:GAMEOBJECT:8000022"
    assert flow.tdb_use_spot({**at_spot, "monotonic_time": 25.}, 55639, 62.7)["hint"] == "spawn:GAMEOBJECT:8000022"
    # 20 s without credit: the next spawn on this floor (none within 25 yd).
    assert flow.tdb_use_spot({**at_spot, "monotonic_time": 31.}, 55639, 62.7) is None
    # Combat at the spot does not count as searching it.
    flow = ObjectInteractionFlow()
    flow.tdb_use_spot(at_spot, 55639, 62.7)
    flow.tdb_use_spot({**at_spot, "monotonic_time": 25., "is_in_combat": True}, 55639, 62.7)
    assert flow.tdb_use_spot({**at_spot, "monotonic_time": 31.}, 55639, 62.7) is not None


def test_a_cocoon_on_another_floor_does_not_stop_the_floor_walk():
    """14:07:18-14:08:36: every floor-walk MOVE ended at once with
    quest_object_visible; the agent stood a minute on one spot."""
    from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
    move = SimpleNamespace(proposal=SimpleNamespace(skill="MOVE", parameters={
        "purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "quest_id": 55639, "x": 95.5, "y": -2280.2}))
    box = {"source": "WORLD3D", "candidate_labels": ["quest_object_like"], "confidence": .8,
           "stable_frames": 5, "bbox_height_fraction": .39, "track_id": "WORLD3D:613"}
    state = {**_state(x=76.5, y=-2269.9), "visual_candidates": [box]}
    assert movement_visual_interrupt(move, state)["reason"] == "quest_object_visible"
    assert movement_visual_interrupt(move, state, object_at_hand=lambda qid: None)["reason"] == "quest_object_visible"
    assert movement_visual_interrupt(move, state, object_at_hand=lambda qid: True)["reason"] == "quest_object_visible"
    assert movement_visual_interrupt(move, state, object_at_hand=lambda qid: False) is None


# --- 20:15-20:18 run: the floor and the objective kind were missing ---------------

def test_the_player_floor_survives_the_runtime_vs_addon_clock_skew():
    """20:15:59: the resolver's sample (runtime clock) was 0.2 s newer than
    the state's addon sample time; the lookup called it stale, the pit
    bottom was chosen and no cocoon spot was known (clicks from 17.6 yd)."""
    nav = NavigationService()
    nav._z.player = ResolvedPosition(94.8, -2248.6, 95.48, .5, "MMAP", 2175, at=27499.9)
    state = {**_state(x=94.8, y=-2248.6), "monotonic_time": 27499.66}
    assert nav.player_layer_z(state) == 95.48
    assert nav.player_layer_z({**state, "monotonic_time": None}) == 95.48


def test_the_first_sample_after_accepting_already_counts_as_a_multi_floor_cocoon_set():
    """20:15:59: the objective came with progress only (no text, no type);
    the spawn MOVE to the pit bottom started in that very tick."""
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    bare = {**_state(), "active_quests": [{"quest_id": 55639, "is_complete": False,
                                           "objectives": [{"current": 0.}]}]}
    assert len(QuestLocationPlanningPolicy.multi_level_spawns(bare, 55639)) == 5
    # A known non-object objective never borrows the object spawns.
    kill = {**_state(), "active_quests": [{"quest_id": 55639, "is_complete": False, "objectives": [
        {"current": 0, "raw_type": "monster", "type": "KILL", "description": "Spiders slain"}]}]}
    assert QuestLocationPlanningPolicy.multi_level_spawns(kill, 55639) == []
    assert _objective_proposals({**bare}, layer=95.48) == []


# --- 20:24-20:35 run: 4/5, then the last cocoon --------------------------------------

def test_anywhere_in_the_pit_counts_as_inside_the_zone():
    """20:25:39: after the first cocoon the walk stood at (105.8, -2288.9),
    27 yd from the nearest spawn, and climbed back to the rim POI."""
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    policy = QuestLocationPlanningPolicy()
    poi = {"x": 81., "y": -2242., "instance_id": 2175}
    assert policy._within_objective_area(poi, _state(x=105.8, y=-2288.9), 55639)
    assert not policy._within_objective_area(poi, _state(x=200., y=-2288.9), 55639)


class _PitBottom:
    """Two floors at the 5th cocoon: the pit bottom (-5.3, headroom-flagged)
    and the spiral 41 yd above it, both reachable (bottom path shorter)."""

    def walkable_heights_at(self, instance_id, point, radius=2.5):
        return [-5.3, 41.2]

    def vmap_surfaces_at(self, instance_id, point):
        return [-5.3, -4.2, 41.2]                    # something 1.1 yd above the bottom

    def find_path(self, instance_id, start, end):
        return SimpleNamespace(anchors=({"x": start["x"], "y": start["y"], "z": start["z"]},
                                        {"x": end["x"], "y": end["y"], "z": end["z"]}),
                               cost=92. if end["z"] < 0 else 219.)


def test_a_yellow_dot_keeps_its_own_floor_over_a_storey_above_it():
    """20:31:13: the dot of the 5th cocoon resolved to the spiral 41 yd above
    the pit bottom the player stood on; the route climbed the spiral."""
    from wowbot.navigation.z_resolver import ZResolver
    resolver = ZResolver(_PitBottom())
    player = ResolvedPosition(63., -2270.1, .3, .85, "MMAP", 2175, at=1.)
    target = resolver.resolve_target(2175, 124.5, -2238.3, player=player, floor_hint="SAME")
    assert target is not None and target.z == -5.3


def test_a_down_arrow_on_the_focused_yellow_dot_releases_it_for_the_floor_walk():
    """User 20:36: "it did not see the down arrow on the last one".  From
    20:31:57 the dot was drawn BELOW, yet its same-floor local search kept
    repeating and held the floor walk back."""
    import wowbot.agent.quest_location_planning as module
    from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
    policy = QuestLocationPlanningPolicy()
    state = _state(x=125.5, y=-2247.5)
    policy.dot_focus.select(state, [(124.5, -2238.3, "55639")], x=125.5, y=-2247.5, now=10.)
    assert policy.dot_focus.focus is not None and policy.dot_focus.remembered
    original_cues, original_dots = module.minimap_vertical_objective_cues, module.minimap_objective_dots
    module.minimap_vertical_objective_cues = lambda _state: [(124.7, -2238.2, "55639", "BELOW", 11.)]
    module.minimap_objective_dots = lambda *_a, **_k: []
    try:
        assert policy.minimap_dot_move(SimpleNamespace(state={**state, "monotonic_time": 11.})) is None
        assert policy.dot_focus.focus is None and not policy.dot_focus.remembered
        # Still drawn yellow in the same sample (a cocoon right above/below): kept.
        policy.dot_focus.select(state, [(124.5, -2238.3, "55639")], x=125.5, y=-2247.5, now=12.)
        module.minimap_objective_dots = lambda *_a, **_k: [(124.5, -2238.3, "55639")]
        policy.minimap_dot_move(SimpleNamespace(state={**state, "monotonic_time": 13.}))
        assert policy.dot_focus.focus is not None
    finally:
        module.minimap_vertical_objective_cues, module.minimap_objective_dots = original_cues, original_dots


def test_tiny_yellow_specks_near_the_player_arrow_are_not_objective_dots():
    """2-5 px "dots" (36 samples a run, real ones 17-24 px) kept "same space"
    true and drew dot moves."""
    from wowbot.agent.quest_location_planning import minimap_objective_dots
    def with_dots(*dots):
        return {**_state(x=80., y=-2250.), "orientation": 0., "minimap_geometry": {"view_radius_yards": 100.},
                "quest_locations": [{"quest_id": 55639, "world_position": {
                    "x": 81., "y": -2242., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}],
                "visual_candidates": [{"kind": "minimap_quest_dot", "view_radius_yards": 100.,
                                       "dots": list(dots)}]}
    real = {"offset": [.05, -.3], "floor": "SAME", "pixels": 22}
    speck = {"offset": [.05, -.05], "floor": "SAME", "pixels": 2}
    assert len(minimap_objective_dots(with_dots(real, speck))) == 1
    assert minimap_objective_dots(with_dots(speck)) == []
