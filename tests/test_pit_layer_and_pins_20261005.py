"""Live 2026-10-05 12:23-12:26 (pid 2456).

* "Who Lurks in the Pit": the quest POI sits on the rim of Hrun's pit, the
  cocoons ~110 yd below on a spiral path (user: "spirálisan megy lefelé egy
  út").  "Within the area" was a 2D test, so the agent searched the rim,
  opened the map and talked to Bjorn.
* After the turn-in the agent left for Private Cole's pin before Alaria's new
  pin appeared next to it, and later took a 155 yd detour east when Alaria's
  route was briefly blocked (user: "oda-vissza ment").
* Private Cole was hovered three times with a "!" over his box, never selected.
* The cocoon objective (raw type ``object``) made every friendly NPC relevant.
"""
from types import SimpleNamespace

from wowbot.agent.map_poi_planning import MapPoiPlanningPolicy
from wowbot.agent.models import Proposal
from wowbot.agent.navigation_planning import NavigationProposalAdapter
from wowbot.agent.quest_giver_evidence import friendly_npc_relevant, npc_objective_subjects, npc_shows_quest_symbol
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy

POI = {"quest_id": 55639, "map_id": 1409, "x": .5096, "y": .5999, "source": "QUEST_POI", "in_progress": True,
       "world_position": {"x": 81., "y": -2242., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}
PIT_QUEST = {"quest_id": 55639, "is_complete": False, "title": "Who Lurks in the Pit", "objectives": [
    {"description": "0/5 Trapped Expedition Member rescued from cocoons", "current": 0, "required": 5,
     "type": "INTERACT", "raw_type": "object"}]}
BOTTOM = {"x": 85.9, "y": -2208., "z": -21.1, "z_known": True, "layer_z": -21.1,
          "z_source": "NAVMESH_LOWER_LAYER", "drop_yards": 117.}


def _world(t=1., texts=None, oracle=lambda state, destination: dict(BOTTOM)):
    state = {"monotonic_time": t, "map_id": 1409, "active_quests": [PIT_QUEST], "quest_locations": [POI],
             "player_world_position": {"x": 93.2, "y": -2249.1, "instance_id": 2175}}
    model = SimpleNamespace(state=state)
    model.__dict__.update({"layer_oracle": oracle, "quest_texts": texts or {}})
    return SimpleNamespace(state=state, _model=model, query=SimpleNamespace(remembered_locations=lambda kinds: []),
                           distance=lambda params: None)


def _moves(policy, world):
    return [p for p in policy.propose_known_locations(world) if p.skill == "MOVE"]


def test_quest_text_pointing_down_sends_the_agent_to_the_layer_below():
    texts = {"55639": {"description": "I fear it will be up to you to make the descent and save the survivors."
                                      " With our luck, the last survivor is at the bottom of the pit."}}
    moves = _moves(QuestLocationPlanningPolicy(), _world(texts=texts))
    assert len(moves) == 1
    move = moves[0]
    assert (move.parameters["z"], move.parameters["z_known"], move.parameters["destination_layer"]) == (-21.1, True, "LOWER")
    assert move.priority == 80 and move.parameters["layer_cue"] == "QUEST_TEXT"


def test_zone_exploration_starts_at_the_zone_without_waiting():
    """User: at the zone (edge) the exploration starts at once -- not first a
    rim search, not first the centre.  Without a text cue it ranks below the
    local seek/inspect/yellow-dot moves."""
    moves = _moves(QuestLocationPlanningPolicy(), _world(t=1.))
    assert len(moves) == 1 and moves[0].priority == 62
    assert moves[0].parameters["layer_cue"] == "ZONE_HAS_LOWER_FLOORS"


def test_no_lower_floor_or_a_finished_sweep_gives_no_move():
    texts = {"55639": {"description": "the bottom of the pit"}}
    assert _moves(QuestLocationPlanningPolicy(), _world(texts=texts, oracle=lambda s, d: None)) == []
    world = _world(texts=texts)
    world._model.__dict__["zone_sweep"] = lambda state, destination, key: None     # swept down and up
    assert _moves(QuestLocationPlanningPolicy(), world) == []


def test_game_object_objectives_do_not_make_friendly_npcs_relevant():
    cocoon = SimpleNamespace(type="INTERACT", target_entity={}, raw={"raw_type": "object"},
                             description="0/5 Trapped Expedition Member rescued from cocoons")
    state = {"active_quests": [PIT_QUEST]}
    assert not friendly_npc_relevant(state, "Creature-0-3113-2175-63341-156891-0000", {"INTERACT"},
                                     unit_name="Bjorn Stouthands", npc_subjects=npc_objective_subjects([cocoon]))
    talk = SimpleNamespace(type="INTERACT", target_entity={}, raw={"raw_type": "monster"},
                           description="0/1 Survivor calmed")
    assert friendly_npc_relevant(state, "Creature-0-3113-2175-63341-156891-0000", {"INTERACT"},
                                 unit_name="Bjorn Stouthands", npc_subjects=npc_objective_subjects([talk]))


def test_quest_symbol_over_the_box_under_the_cursor_counts():
    """The hover is bound to a probed box beside Cole; the "!" is over his own box."""
    cole = "Creature-0-3113-2175-63341-156801-0000C115E3"

    def box(track, kind, x, y, w, h, bbox):
        return {"source": "WORLD3D", "track_id": track, "kind": kind, "detector_kind": kind,
                "x": x, "y": y, "bbox_width_fraction": w, "bbox_height_fraction": h,
                "candidate_labels": ["learned_symbol_like"] if "symbol" in kind else [],
                "bbox": {**bbox, "coordinate_space": "CLIENT_PIXELS"}}
    body = box("WORLD3D:cole", "unknown_subject_candidate", .477, .589, .031, .114,
               {"left": 389, "top": 168, "right": 415, "bottom": 222})
    bang = box("WORLD3D:bang", "unknown_symbol_candidate", .477, .69, .014, .042,
               {"left": 396, "top": 137, "right": 408, "bottom": 157})
    probe = box("WORLD3D:probe", "unknown_subject_candidate", .51, .64, .018, .046,
                {"left": 422, "top": 160, "right": 437, "bottom": 182})
    state = {"visual_candidates": [body, bang, probe], "mouseover": {"guid": cole, "name": "Private Cole"},
             "cursor_position": {"nx": .497, "ny": .617},
             "confirmed_mouseover_anchors": {cole: {"track_id": "WORLD3D:probe"}}}
    assert npc_shows_quest_symbol(state, cole)
    elsewhere = {**state, "cursor_position": {"nx": .9, "ny": .1}}
    assert not npc_shows_quest_symbol(elsewhere, cole)


def test_pin_routes_wait_for_the_new_pins_after_a_turn_in():
    policy = MapPoiPlanningPolicy()

    def pin(qid, x, y):
        return {"quest_id": qid, "is_campaign": True, "x": .5, "y": .5, "source": "QUESTLINE_API",
                "world_position": {"x": x, "y": y, "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}
    old_pins = [pin(55196, 267., -2339.), pin(58914, 187., -2280.)]

    def world(t, active, pins):
        return SimpleNamespace(state={"monotonic_time": t, "active_quests": active, "map_pois": {"available_quests": pins},
                                      "player_world_position": {"x": 95., "y": -2248., "instance_id": 2175}})
    assert policy.quest_giver_moves(world(1., [{"quest_id": 55965, "is_campaign": True}], old_pins)) == []      # campaign in progress
    assert policy.quest_giver_moves(world(2., [], old_pins)) == []                        # just turned in: settle
    assert policy.quest_giver_moves(world(6., [], old_pins)) == []
    new = policy.quest_giver_moves(world(9., [], old_pins + [pin(55639, 97., -2249.)]))
    # The new pin is 2 yd away (reached, local search) -> the next route is Cole's.
    assert [p.parameters["quest_id"] for p in new][:1] == [58914]
    assert 55639 not in [p.parameters["quest_id"] for p in new]
    assert policy.quest_giver_moves(world(20., [], old_pins))                            # settle window over


def test_a_blocked_route_does_not_turn_into_a_long_detour():
    near = Proposal.make("MOVE", "Alaria", {"x": 97., "y": -2249., "coordinate_space": "WORLD_YARDS",
                                            "quest_id": 55639}, confidence=.75, priority=84)
    far = Proposal.make("MOVE", "Harpy", {"x": 267., "y": -2339., "coordinate_space": "WORLD_YARDS",
                                          "quest_id": 55196}, confidence=.75, priority=83.5)
    position = (131.4, -2267.0)
    world = SimpleNamespace(distance=lambda p: ((p["x"]-position[0])**2 + (p["y"]-position[1])**2) ** .5)
    assert NavigationProposalAdapter._much_farther(world, far, world.distance(near.parameters))
    assert not NavigationProposalAdapter._much_farther(world, near, world.distance(far.parameters))


def _with_minimap(world, labels=(), kind="learned_minimap_marker", dots=None):
    world.state["visual_candidates"] = [{"source": "MINIMAP_CV", "kind": kind, "candidate_labels": list(labels),
                                         **({"dots": dots} if dots else {})}]
    return world


def test_minimap_grey_dot_below_is_a_strong_cue_and_yellow_means_same_space():
    """User 2026-10-05: yellow = same space as the objective; grey = a space we
    are not in; a down/up arrow = lower/higher than us."""
    below = _with_minimap(_world(t=1.), ["quest_objective_dot_like", "other_space_like", "objective_below_like"])
    moves = _moves(QuestLocationPlanningPolicy(), below)
    assert len(moves) == 1 and moves[0].priority == 80
    assert moves[0].parameters["layer_cue"] == "MINIMAP_OBJECTIVE_BELOW"
    policy = QuestLocationPlanningPolicy()
    yellow = _with_minimap(_world(t=40.), ["quest_objective_dot_like"], kind="minimap_quest_dot",
                           dots=[{"offset": [.1, .05]}])
    yellow.state["visual_candidates"][0]["view_radius_yards"] = 160.
    purposes = [(m.parameters.get("purpose"), m.parameters.get("destination_layer")) for m in _moves(policy, yellow)]
    assert purposes == [("APPROACH_MINIMAP_QUEST_DOT", None)]  # same space: walk to the dot, no descent
    assert len(_moves(policy, _world(t=41.))) == 1             # without the dot the sweep goes on


def test_minimap_vocabulary_has_the_floor_classes():
    from wowbot.vision.map_markers import CLASS_APPEARANCE_LABELS, MAP_MARKER_YOLO_CLASSES
    assert MAP_MARKER_YOLO_CLASSES[:9][-1] == "player_arrow"          # old label ids unchanged
    assert "objective_below_like" in CLASS_APPEARANCE_LABELS["objective_dot_below"]
    assert "objective_above_like" in CLASS_APPEARANCE_LABELS["objective_dot_above"]
    assert "same_space_like" in CLASS_APPEARANCE_LABELS["objective_dot_same_space"]


def test_quest_giver_icon_on_the_minimap_is_not_an_objective_dot():
    """Live 12:53: Private Cole's yellow "!" (13.6 yd from his pin) was walked to."""
    from wowbot.agent.quest_location_planning import minimap_objective_dots
    world = _world(t=1.)
    world.state["player_world_position"] = {"x": 94., "y": -2250., "instance_id": 2175}
    world.state["orientation"] = 0.
    world.state["map_pois"] = {"available_quests": [{"quest_id": 58914, "world_position": {
        "x": 187., "y": -2280., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}]}
    from wowbot.vision.minimap_quest_area import offsets_to_world
    # find an offset that lands ~10 yd from Cole's pin
    cand = {"source": "MINIMAP_CV", "kind": "minimap_quest_dot", "view_radius_yards": 233.,
            "dots": [{"offset": [0., 0.]}]}
    for ox in [i/100 for i in range(-60, 61)]:
        for oy in [i/100 for i in range(-60, 61)]:
            (x, y), = offsets_to_world([[ox, oy]], player_x=94., player_y=-2250., view_radius_yards=233.,
                                       rotate=False, facing=0.)
            if abs(x-196.) < 2 and abs(y+2280.) < 2:
                cand["dots"] = [{"offset": [ox, oy]}]
    world.state["visual_candidates"] = [cand]
    assert minimap_objective_dots(world.state) == []
    world.state["map_pois"] = {"available_quests": []}
    assert len(minimap_objective_dots(world.state)) == 1


def test_entering_the_blue_area_ends_the_route_unless_the_objective_is_on_another_floor():
    from wowbot.agent.engine_runtime_projection import quest_zone_entered
    params = {"purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "quest_id": 55639, "x": 81., "y": -2242.}
    area = {"source": "MINIMAP_CV", "kind": "minimap_quest_area", "view_radius_yards": 160.,
            "quest_area": {"player_inside": True}}
    state = {"player_world_position": {"x": 120., "y": -2260.}, "visual_candidates": [area]}
    assert quest_zone_entered(params, state)["kind"] == "QUEST_ZONE_ENTERED"
    grey_below = {"source": "MINIMAP_LEARNED", "candidate_labels": ["objective_below_like"]}
    assert quest_zone_entered(params, {**state, "visual_candidates": [area, grey_below]}) is None
    outside = {**area, "quest_area": {"player_inside": False}}
    assert quest_zone_entered(params, {**state, "visual_candidates": [outside]}) is None
    # The descent ends only when an objective dot is yellow (same space).
    descent = {**params, "destination_layer": "LOWER", "x": 85.9, "y": -2208.}
    assert quest_zone_entered(descent, state) is None


class _LayerMesh:
    """Two walkable layers everywhere: the rim (98) and the spiral (64)."""
    layers = (98., 64.)

    def __init__(self):
        self.paths = []

    def project_position(self, instance_id, point, *, z_hint=None):
        z = min(self.layers, key=lambda h: abs(h-(98. if z_hint is None else z_hint)))
        return {"x": point["x"], "y": point["y"], "z": z, "instance_id": instance_id}

    def find_path(self, instance_id, start, destination):
        self.paths.append(dict(start))
        return None

    def supports(self, instance_id):
        return True

    def walkable_heights_at(self, instance_id, point, radius=2.5):
        return sorted(self.layers)


def test_a_new_route_starts_on_the_tracked_layer_not_on_the_rim_above():
    """Live 12:55: after a spider fight on the 64 yd ledge the route restarted
    from the terrain height (the rim, 98) and the agent walked on the spot."""
    from wowbot.navigation.service import NavigationService
    mesh = _LayerMesh()
    nav = NavigationService(navmesh=mesh)
    # 2026-10-06: the Z resolver follows the own layer (first fix from the route).
    on_route = {"player_world_position": {"x": 83., "y": -2269., "instance_id": 2175}}
    nav._z.observe_player(on_route, 10., route_z=64.)
    moved = {"player_world_position": {"x": 78.6, "y": -2272.2, "instance_id": 2175, "z_known": False}}
    nav._z.observe_player(moved, 12.)
    started = nav._state_with_layer_continuity(moved, 20.)["player_world_position"]
    assert (started["z"], started["z_estimated"], started["z_source"]) == (64., True, "NAVMESH_LAYER_CONTINUITY")
    # Far away or long ago: the terrain fallback (and its layer probe) stays.
    far = {"player_world_position": {"x": 200., "y": -2272.2, "instance_id": 2175, "z_known": False}}
    assert "z" not in nav._state_with_layer_continuity(far, 20.)["player_world_position"]
    assert "z" not in nav._state_with_layer_continuity(moved, 400.)["player_world_position"]


def test_estimated_heights_keep_their_flags_into_the_navmesh():
    """The Torgok/Wrathion layer probe needs to know the start height is only an estimate."""
    from types import SimpleNamespace as NS
    from wowbot.navigation.global_planner import GlobalNavigator
    mesh = _LayerMesh()
    planner = GlobalNavigator(navmesh=mesh)
    state = {"player_world_position": {"x": 78.6, "y": -2272.2, "z": 64., "z_known": True, "z_estimated": True,
                                       "z_source": "NAVMESH_LAYER_CONTINUITY", "instance_id": 2175,
                                       "coordinate_space": "WORLD_YARDS"}}
    request = NS(destination={"x": 85.9, "y": -2208., "z": -21.1, "z_known": True, "z_estimated": True,
                              "z_source": "NAVMESH_LOWER_LAYER", "coordinate_space": "WORLD_YARDS",
                              "instance_id": 2175})
    planner._navmesh_path(request, state, {"x": 78.6, "y": -2272.2, "z": 64.}, {"x": 85.9, "y": -2208., "z": -21.1})
    start = mesh.paths[-1]
    assert (start["z"], start["z_estimated"], start["z_source"]) == (64., True, "NAVMESH_LAYER_CONTINUITY")


class _SpiralMesh(_LayerMesh):
    """A straight 'spiral' from the rim (98) down to the bottom (-20)."""

    def find_path(self, instance_id, start, destination):
        from types import SimpleNamespace as NS
        anchors = [{"x": 80. + i, "y": -2240., "z": 98. - 2.*i} for i in range(60)]
        return NS(anchors=anchors, cost=118.)


def test_zone_sweep_walks_the_floors_in_hops_down_then_up():
    from wowbot.navigation.service import NavigationService
    nav = NavigationService(navmesh=_SpiralMesh())
    nav.lower_layer_point = lambda state, destination: {"x": 139., "y": -2240., "z": -20.}
    at = {"player_world_position": {"x": 80., "y": -2240., "instance_id": 2175}}
    first = nav.zone_sweep_next(at, {"x": 81., "y": -2242.}, "pit")
    assert first["sweep_direction"] == "DOWN" and first["sweep_hop"] == 0
    hops = first["sweep_hops"]
    assert hops >= 7                                   # ~130 yd of path in 15 yd hops
    # Standing at the bottom: the remaining hops are walked back up.
    nav._player_layer = (2175, 139., -2240., -20., 1.)
    bottom = {"player_world_position": {"x": 139., "y": -2240., "instance_id": 2175}}
    up = nav.zone_sweep_next(bottom, {"x": 81., "y": -2242.}, "pit")
    assert up["sweep_direction"] == "UP" and up["sweep_hop"] == hops-2
