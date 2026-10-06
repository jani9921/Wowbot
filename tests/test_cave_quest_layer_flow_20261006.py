"""Generic stacked-floor quest regressions from the 2026-10-06 cave run.

Offline tests prove state transitions only.  They are not live quest credit.
"""
from types import SimpleNamespace

from wowbot.agent.quest_dot_focus import QuestDotFocus
from wowbot.agent.quest_location_planning import QuestLocationPlanningPolicy
from wowbot.navigation.service import NavigationService
from wowbot.navigation.z_resolver import ResolvedPosition, ZResolver


QUEST = {"quest_id": 55639, "is_complete": False,
         "objectives": [{"objective_id": "55639:0", "description": "Rescue members from cocoons",
                         "raw_type": "object", "type": "INTERACT", "current": 2,
                         "required": 5, "is_complete": False}]}


def _state(t, x=0., dots=()):
    return {"session_id": "cave", "map_id": 1409, "monotonic_time": float(t),
            "player_world_position": {"x": x, "y": 0., "instance_id": 2175,
                                      "coordinate_space": "WORLD_YARDS"},
            "active_quests": [QUEST], "test_dots": list(dots), "quest_locations": [],
            "visual_candidates": []}


def _world(state):
    return SimpleNamespace(state=state, query=SimpleNamespace(remembered_locations=lambda *_: []))


def test_occluded_yellow_dot_does_not_switch_to_the_far_dot(monkeypatch):
    monkeypatch.setattr("wowbot.agent.quest_location_planning.minimap_objective_dots",
                        lambda state, **_kwargs: state["test_dots"])
    policy = QuestLocationPlanningPolicy()
    first = policy.minimap_dot_move(_world(_state(1., dots=[(25., 0., "55639"),
                                                           (70., 0., "55639")])))
    assert first.parameters["x"] == 25.
    missing = policy.minimap_dot_move(_world(_state(2., x=5., dots=[(70., 0., "55639")])))
    assert missing.parameters["x"] == 25.
    assert missing.parameters["quest_dot_key"] == first.parameters["quest_dot_key"]


def test_arrival_hands_the_same_room_to_bounded_object_search(monkeypatch):
    monkeypatch.setattr("wowbot.agent.quest_location_planning.minimap_objective_dots",
                        lambda state, **_kwargs: state["test_dots"])
    policy = QuestLocationPlanningPolicy()
    policy.propose_known_locations(_world(_state(1., dots=[(25., 0., "55639"),
                                                              (70., 0., "55639")])))
    arrived = policy.propose_known_locations(_world(_state(4., x=24., dots=[(70., 0., "55639")])))
    searches = [p for p in arrived if p.skill == "SEEK_VISUAL_CUE"]
    assert len(searches) == 1
    assert searches[0].parameters["purpose"] == "SEARCH_LOCAL_OBJECT"
    assert searches[0].parameters["search_area"]["floor_hint"] == "SAME"
    immediate = policy.propose_known_locations(_world(_state(5., x=24., dots=[(70., 0., "55639")])))
    assert not any(p.skill == "SEEK_VISUAL_CUE" for p in immediate)
    # A bounded search without credit can move on; it cannot reselect the
    # same dot forever merely because that marker remains visible.
    later = policy.minimap_dot_move(_world(_state(35., x=24., dots=[(25., 0., "55639"),
                                                                  (70., 0., "55639")])))
    assert later.parameters["x"] == 70.


def test_credit_change_unlocks_an_exhausted_objective_dot():
    memory = QuestDotFocus()
    state = _state(1.)
    assert memory.select(state, [(25., 0., "55639")], x=0., y=0., now=1.) is not None
    memory.arrived(2.)
    assert memory.select(_state(35.), [(25., 0., "55639")], x=25., y=0., now=35.) is None
    changed = _state(36.)
    changed["active_quests"] = [{**QUEST, "objectives": [{**QUEST["objectives"][0], "current": 3}]}]
    assert memory.select(changed, [(25., 0., "55639")], x=25., y=0., now=36.) is not None


class _Stacked:
    def walkable_heights_at(self, _instance, _point, _radius=2.5):
        return [0., 30.]

    def terrain_sample(self, _instance, _point):
        return SimpleNamespace(terrain_z=30., is_hole=False)


def test_repeated_stacked_samples_do_not_promote_a_guessed_floor():
    resolver = ZResolver(_Stacked())
    position = {"player_world_position": {"x": 0., "y": 0., "instance_id": 2175}}
    first = resolver.observe_player(position, 1.)
    again = resolver.observe_player(position, 2.)
    assert first.confidence == again.confidence == .5
    assert again.alternatives == (0.,)


def test_neighboring_polygons_on_one_slope_are_not_two_storeys():
    class _Refs:
        def walkable_layers_at(self, _instance, _point, _radius=2.5):
            return [{"z": 30., "layer_id": ("detour", 10)},
                    {"z": 30.3, "layer_id": ("detour", 11)}]

    resolver = ZResolver(_Refs())
    position = resolver.observe_player(
        {"player_world_position": {"x": 0., "y": 0., "instance_id": 2175}}, 1.)
    assert position.confidence == .95 and position.layer_id == ("detour", 11)


def test_ambiguous_first_fix_refuses_a_long_cave_route():
    nav = NavigationService(navmesh=_Stacked())
    state = _state(1.)
    nav.start_skill_request("MOVE", {"x": 100., "y": 0., "instance_id": 2175,
                                     "coordinate_space": "WORLD_YARDS", "require_navmesh": True},
                            state, "obs", 1.)
    result = nav.observe(_state(2.), "obs2", 2.)
    # Without any path query no hypothesis can be probed: fail closed.
    assert result.terminal and not result.success and result.reason == "ambiguous_player_layer"


def test_ambiguous_first_fix_walks_only_a_short_probe_leg():
    """Live 2026-10-06 20:08 (agent started in the pit): failing every MOVE
    on an ambiguous floor left the character standing for 45 s; only motion
    resolves the floor.  A 12 yd leg from the likeliest floor, not the route."""
    class _StackedPaths(_Stacked):
        def find_path(self, _instance, start, end):
            anchors = tuple({"x": float(x), "y": 0., "z": start.get("z", 0.)} for x in range(0, 101, 5))
            return SimpleNamespace(anchors=anchors, cost=100., tile_count=1, polygon_count=2)

    nav = NavigationService(navmesh=_StackedPaths())
    nav.start_skill_request("MOVE", {"x": 100., "y": 0., "instance_id": 2175,
                                     "coordinate_space": "WORLD_YARDS", "require_navmesh": True},
                            _state(1.), "obs", 1.)
    assert nav._z.player.confidence == .5 and nav._layer_probe is True
    assert nav._route_failure_reason is None
    assert max(float(anchor["x"]) for anchor in nav._active_route.anchors) <= 15.
    result = nav.observe(_state(2.), "obs2", 2.)
    assert result.reason != "ambiguous_player_layer"


def test_indoors_drops_the_open_surface_over_a_cave():
    """The agent started inside Hrun's pit: terrain (the rim) is the topmost
    layer, the addon says indoors -> the floors below are the hypotheses."""
    class _Pit:
        def walkable_heights_at(self, _instance, _point, _radius=2.5):
            return [-2.7, 45.7, 60.5, 99.0]

        def terrain_sample(self, _instance, _point):
            return SimpleNamespace(terrain_z=98.6, is_hole=False)

    resolver = ZResolver(_Pit())
    sample = {"player_world_position": {"x": 82.9, "y": -2277.6, "instance_id": 2175},
              "movement": {"indoors": True}}
    first = resolver.observe_player(sample, 1.)
    assert first.z == 60.5 and 99.0 not in first.alternatives
    outdoors = ZResolver(_Pit()).observe_player({**sample, "movement": {"indoors": False}}, 1.)
    assert outdoors.z == 99.0


class _EntryFloors:
    """Upper exterior over a cave, with a reachable, arrowed ledge below."""

    def walkable_heights_at(self, _instance, point, _radius=2.5):
        return [61.2] if point["x"] >= 9. else [95.2] if point["x"] >= 4. else [39.7, 95.2]

    def terrain_sample(self, _instance, _point):
        return SimpleNamespace(terrain_z=95.2, is_hole=False)

    def vmap_surfaces_at(self, _instance, point):
        return [61.2] if point["x"] >= 9. else []

    def find_path(self, _instance, start, end):
        return SimpleNamespace(anchors=(start, end), cost=20., tile_count=1, polygon_count=2)


def test_fresh_down_arrow_bootstraps_only_the_unique_surface_layer():
    resolver = ZResolver(_EntryFloors())
    assert resolver.observe_player(_state(1.), 1.).confidence == .5
    ledge = ResolvedPosition(10., 0., 61.2, .89, "COMBINED", 2175,
                             reachable=True, evidence=("vmap_floor", "reachable"))
    assert not resolver.bootstrap_player_from_down_cue(
        ledge, observed_at=-2., indoors=False, now=1.)
    # A downward marker alone also fits a player already inside the cave,
    # with an even lower objective.  The addon must report OUTDOOR now.
    assert not resolver.bootstrap_player_from_down_cue(
        ledge, observed_at=1., indoors=None, now=1.)
    assert not resolver.bootstrap_player_from_down_cue(
        ledge, observed_at=1., indoors=True, now=1.)
    assert resolver.bootstrap_player_from_down_cue(
        ledge, observed_at=1., indoors=False, now=1.)
    assert resolver.player.z == 95.2 and resolver.player.confidence == .7
    assert resolver.player.alternatives == (39.7,)
    # An unchanged stacked X/Y sample cannot turn this hypothesis into fact.
    assert resolver.observe_player(_state(2.), 2.).confidence == .7
    assert resolver.observe_player(_state(3., x=4.), 3.).confidence == .85


def test_down_arrow_probe_expires_and_cannot_restart_at_the_same_stuck_spot():
    resolver = ZResolver(_EntryFloors())
    resolver.observe_player(_state(1.), 1.)
    ledge = ResolvedPosition(10., 0., 61.2, .89, "COMBINED", 2175,
                             reachable=True, evidence=("vmap_floor", "reachable"))
    assert resolver.bootstrap_player_from_down_cue(
        ledge, observed_at=1., indoors=False, now=1.)
    exhausted = resolver.observe_player(_state(47.), 47.)
    assert exhausted.confidence == .5 and "floor_cue_probe_exhausted" in exhausted.evidence
    assert not resolver.bootstrap_player_from_down_cue(
        ledge, observed_at=47., indoors=False, now=47.)


def test_probe_does_not_claim_convergence_when_only_the_lower_floor_remains():
    class _LowerOnly(_EntryFloors):
        def walkable_heights_at(self, instance, point, radius=2.5):
            return [39.7] if point["x"] < 0. else super().walkable_heights_at(instance, point, radius)

    resolver = ZResolver(_LowerOnly())
    resolver.observe_player(_state(1.), 1.)
    ledge = ResolvedPosition(10., 0., 61.2, .89, "COMBINED", 2175,
                             reachable=True, evidence=("vmap_floor", "reachable"))
    assert resolver.bootstrap_player_from_down_cue(
        ledge, observed_at=1., indoors=False, now=1.)
    contradicted = resolver.observe_player(_state(2., x=-4.), 2.)
    assert contradicted.z == 95.2 and contradicted.confidence == .5
    assert "floor_cue_probe_contradicted" in contradicted.evidence


def test_navigation_accepts_fresh_arrow_route_without_claiming_observed_player_z():
    nav = NavigationService(navmesh=_EntryFloors())
    state = _state(1.)
    state["movement"] = {"indoors": False}
    nav.start_skill_request("MOVE", {"x": 10., "y": 0., "instance_id": 2175,
                                     "coordinate_space": "WORLD_YARDS", "require_navmesh": True,
                                     "purpose": "APPROACH_MINIMAP_OTHER_FLOOR_OBJECTIVE",
                                     "floor_hint": "BELOW", "floor_cue_observed_at": 1.},
                            state, "obs", 1.)
    assert nav._z.player.z == 95.2 and nav._z.player.confidence == .7
    assert nav._route_failure_reason != "ambiguous_player_layer"


def test_navigation_does_not_use_an_old_target_to_bootstrap_an_explicit_z_route():
    nav = NavigationService(navmesh=_EntryFloors())
    state = _state(1.)
    state["movement"] = {"indoors": False}
    nav._z.last_target = ResolvedPosition(
        10., 0., 61.2, .89, "COMBINED", 2175,
        reachable=True, evidence=("vmap_floor", "reachable"))
    nav.start_skill_request("MOVE", {"x": 10., "y": 0., "z": 61.2, "z_known": True,
                                     "instance_id": 2175, "coordinate_space": "WORLD_YARDS",
                                     "require_navmesh": True,
                                     "purpose": "APPROACH_MINIMAP_OTHER_FLOOR_OBJECTIVE",
                                     "floor_hint": "BELOW", "floor_cue_observed_at": 1.},
                            state, "obs", 1.)
    assert nav._z.player.confidence == .5
    # Not bootstrapped by the old target: only a short probe leg is walked.
    assert nav._layer_probe is True and nav._route_failure_reason is None


class _Pocket:
    def walkable_heights_at(self, _instance, _point, _radius=2.5):
        return [0.]

    def walkable_points_near(self, _instance, _point, _radius):
        return [{"x": 5., "y": 0., "z": 0.}]

    def find_path(self, _instance, start, end):
        if end["x"] < 4.:
            return None
        return SimpleNamespace(anchors=[start, end], cost=9.)


def test_same_height_disconnected_pocket_does_not_hide_reachable_floor():
    resolver = ZResolver(_Pocket())
    resolver.seed_player(2175, -4., 0., 0., 1.)
    target = resolver.resolve_target(2175, 0., 0., player=resolver.player, floor_hint="SAME")
    assert target is not None and target.reachable is True and target.x == 5.


def test_zone_sweep_never_marks_a_stacked_hop_from_xy_alone():
    nav = NavigationService(navmesh=object())
    nav.__dict__["_zone_sweeps"] = {"cave": {"hops": [{"x": 0., "y": 0., "z": 30.},
                                                    {"x": 0., "y": 0., "z": 0.}],
                                            "visited": set(), "upward": False, "done": False}}
    hop = nav.zone_sweep_next(_state(1.), {}, "cave")
    assert hop["sweep_hop"] == 0
    assert nav.__dict__["_zone_sweeps"]["cave"]["visited"] == set()
    nav._z.seed_player(2175, 0., 0., 30., 2.)
    hop = nav.zone_sweep_next(_state(2.), {}, "cave")
    assert hop["sweep_hop"] == 1
    assert nav.__dict__["_zone_sweeps"]["cave"]["visited"] == {0}


def test_region_coverage_does_not_visit_two_floors_at_the_same_xy():
    from wowbot.navigation.search_coverage import SearchCoveragePlanner

    coverage = SearchCoveragePlanner()
    coverage.begin("cave", {"x": 0., "y": 0., "radius": 12.,
                            "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                            "coverage_points": [{"x": 0., "y": 0., "z": 30.},
                                                {"x": 0., "y": 0., "z": 0.}]})
    coverage.observe("cave", player_x=0., player_y=0., target_detected=False,
                     now=1., player_z=30.)
    cells = coverage.snapshot()["cave"]["cells"]
    assert [cell["visits"] for cell in cells] == [1, 0]
    next_hop = coverage.next_waypoint("cave", player_x=0., player_y=0., player_z=30.)
    assert next_hop["z"] == 0. and next_hop["layer_z"] == 0.
    coverage.observe("cave", player_x=0., player_y=0., target_detected=False,
                     now=2., player_z=None)
    assert coverage.snapshot()["cave"]["cells"][1]["visits"] == 0


def test_same_space_dot_wins_over_unrelated_arrow(monkeypatch):
    from wowbot.agent.engine_runtime_projection import quest_zone_entered
    monkeypatch.setattr("wowbot.agent.quest_location_planning.minimap_objective_dots",
                        lambda _state: [(10., 0., "55639")])
    state = _state(1.)
    state["visual_candidates"] = [{"source": "MINIMAP_CV",
                                    "candidate_labels": ["objective_below_like"]}]
    result = quest_zone_entered({"quest_id": 55639, "destination_layer": "LOWER"}, state)
    assert result["reason"] == "quest_zone_entered_same_space"


def test_up_down_arrow_needs_two_fresh_samples_and_never_becomes_xy_only(monkeypatch):
    from wowbot.agent.quest_location_planning import minimap_vertical_objective_cues

    policy = QuestLocationPlanningPolicy()
    first = _state(1.)
    first["quest_locations"] = [{"quest_id": 55639, "world_position": {
        "x": 32., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}]
    first["visual_candidates"] = [{"kind": "minimap_floor_markers", "source": "MINIMAP_CV",
                                   "view_radius_yards": 160., "observed_at": 1.,
                                   "markers": [{"offset": [0., -.2], "floor": "BELOW"}]}]
    cues = minimap_vertical_objective_cues(first)
    assert len(cues) == 1 and cues[0][2:4] == ("55639", "BELOW")
    assert policy.minimap_vertical_move(_world(first)) is None
    # The same retained perception sample is not a second confirmation.
    assert policy.minimap_vertical_move(_world({**first, "monotonic_time": 1.2})) is None
    second = {**first, "monotonic_time": 2.,
              "visual_candidates": [{**first["visual_candidates"][0], "observed_at": 2.}]}
    move = policy.minimap_vertical_move(_world(second))
    assert move.skill == "MOVE" and move.parameters["floor_hint"] == "BELOW"
    assert move.parameters["require_navmesh"] is True
    assert move.parameters["x"] == 32.


def test_unconfirmed_floor_arrow_does_not_start_a_blind_downward_sweep():
    policy = QuestLocationPlanningPolicy()
    state = _state(1.)
    state["visual_candidates"] = [{"kind": "minimap_floor_markers", "source": "MINIMAP_CV",
                                   "candidate_labels": ["objective_above_like"],
                                   "markers": [{"offset": [.1, 0.], "floor": "ABOVE"}]}]
    location = {"quest_id": 55639, "x": .5, "y": .5}
    destination = {"x": 0., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}
    world = _world(state)
    world._model = SimpleNamespace(zone_sweep=lambda *_: {"x": 9., "y": 9., "z": -20.})
    assert policy._lower_layer_move(world, location, destination, 55639) is None


def test_expired_same_space_dot_does_not_block_a_later_layer_sweep():
    policy = QuestLocationPlanningPolicy()
    policy.dot_focus.select(_state(1.), [(25., 0., "55639")], x=0., y=0., now=1.)
    state = _state(25.)
    world = _world(state)
    world._model = SimpleNamespace(zone_sweep=lambda *_: {"x": 9., "y": 9., "z": -20.})
    location = {"quest_id": 55639, "x": .5, "y": .5}
    destination = {"x": 0., "y": 0., "instance_id": 2175,
                   "coordinate_space": "WORLD_YARDS"}
    assert policy._lower_layer_move(world, location, destination, 55639).skill == "MOVE"


def test_floor_direction_restricts_target_candidates():
    class _Floors(_Pocket):
        def walkable_heights_at(self, _instance, _point, _radius=2.5):
            return [0., 30.]

        def walkable_points_near(self, _instance, _point, _radius):
            return []

        def find_path(self, _instance, start, end):
            return SimpleNamespace(anchors=[start, end], cost=35.)

    resolver = ZResolver(_Floors())
    resolver.seed_player(2175, -4., 0., 30., 1.)
    below = resolver.resolve_target(2175, 0., 0., player=resolver.player, floor_hint="BELOW")
    assert below is not None and below.z == 0.
    above = resolver.resolve_target(2175, 0., 0., player=resolver.player, floor_hint="ABOVE")
    assert above is None and resolver.last_target_failure == "no_layer_matching_floor_cue"


def test_turnin_xy_arrival_does_not_hide_a_known_floor_mismatch():
    policy = QuestLocationPlanningPolicy()
    state = _state(1.)
    state["player_world_position"].update({"z": 0., "z_known": True, "z_confidence": .9})
    destination = {"x": 0., "y": 0., "z": 30., "z_known": True,
                   "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}
    assert not policy.turn_in_arrived(55639, destination, state)
    state["player_world_position"]["z"] = 30.
    assert policy.turn_in_arrived(55639, destination, state)


def test_verified_turnin_route_keeps_its_floor_during_local_npc_search():
    policy = QuestLocationPlanningPolicy()
    state = _state(1.)
    state["player_world_position"].update({"z": 30., "z_known": True, "z_confidence": .9})
    route = {"x": 0., "y": 0., "z": 30., "z_known": True, "z_confidence": .86,
             "quest_id": 55639, "purpose": "LOCATE_TURN_IN_REGION",
             "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}
    policy.mark_reached(route, state)
    api_pin = {"x": 0., "y": 0., "instance_id": 2175,
               "coordinate_space": "WORLD_YARDS"}
    assert policy.turn_in_arrived(55639, api_pin, state)
    assert policy.turn_in_search(55639, api_pin).parameters["search_area"]["z"] == 30.
    state["player_world_position"]["z"] = 0.
    assert not policy.turn_in_arrived(55639, api_pin, state)
    state["player_world_position"]["z_confidence"] = .4
    assert policy.turn_in_arrived(55639, api_pin, state)


def test_turnin_search_cell_keeps_z_and_stops_after_a_bounded_search():
    from wowbot.agent.navigation_planning import NavigationProposalAdapter

    visited = []
    navigation = SimpleNamespace(
        begin_search_region=lambda *_: None,
        observe_search_region=lambda *_args, **_kwargs: None,
        next_search_waypoint=lambda *_: {"x": 0., "y": 0., "z": 30.,
                                         "search_cell_id": "upper"},
        mark_search_cell_visited=lambda *_args: visited.append(_args[1]))
    adapter = NavigationProposalAdapter(navigation)
    proposal = QuestLocationPlanningPolicy().turn_in_search(
        55639, {"x": 0., "y": 0., "z": 30., "instance_id": 2175,
                "coordinate_space": "WORLD_YARDS"})

    def adapt(t, z, last=None):
        state = _state(t)
        state["player_world_position"].update({"z": z, "z_confidence": .9})
        return adapter._search_waypoint(proposal, _world(state), t, last_result=last)

    assert adapt(1., 0.).skill == "SEEK_VISUAL_CUE"
    found = {"skill": "SEEK_VISUAL_CUE", "purpose": "SEARCH_TURN_IN_AREA", "action_id": "a1"}
    move = adapt(2., 0., found)
    assert move.skill == "MOVE" and move.parameters["z"] == 30.
    assert adapt(3., 0., found).parameters["z"] == 30.
    assert visited == []   # same X/Y on the cave floor is not cell arrival
    assert adapt(4., 30., found).skill == "SEEK_VISUAL_CUE"
    assert visited == ["upper"]
    assert adapt(122., 30., found).skill == "SEEK_VISUAL_CUE"  # new verified floor
    expired = adapt(243., 30., found)
    assert expired.skill == "WAIT"
    assert expired.parameters["replan_scope"] == "QUEST_OR_FLOOR_EVIDENCE"


def test_stale_player_layer_cannot_visit_a_stacked_search_cell():
    nav = NavigationService(navmesh=object())
    nav.begin_search_region("cave", {"x": 0., "y": 0., "radius": 12.,
                                     "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                                     "coverage_points": [{"x": 0., "y": 0., "z": 30.}]})
    nav._z.seed_player(2175, 0., 0., 30., 1.)
    nav.observe_search_region("cave", _state(5.), 5., target_detected=False)
    assert nav._search_coverage.snapshot()["cave"]["cells"][0]["visits"] == 0
    nav.observe_search_region("cave", _state(1., x=20.), 1., target_detected=False)
    assert nav._search_coverage.snapshot()["cave"]["cells"][0]["visits"] == 0
    nav.observe_search_region("cave", _state(1.), 1., target_detected=False)
    assert nav._search_coverage.snapshot()["cave"]["cells"][0]["visits"] == 1


def test_malformed_floor_marker_offset_is_not_navigation_evidence():
    from wowbot.agent.quest_location_planning import minimap_vertical_objective_cues

    state = _state(1.)
    state["quest_locations"] = [{"quest_id": 55639, "world_position": {
        "x": 32., "y": 0., "instance_id": 2175, "coordinate_space": "WORLD_YARDS"}}]
    state["visual_candidates"] = [{"kind": "minimap_floor_markers", "source": "MINIMAP_CV",
                                   "view_radius_yards": 160., "observed_at": 1.,
                                   "markers": [{"offset": [0.], "floor": "BELOW"},
                                               {"offset": [float("nan"), 0.], "floor": "ABOVE"}]}]
    assert minimap_vertical_objective_cues(state) == []


def test_weak_quest_outline_is_hovered_only_in_a_quest_object_search():
    from wowbot.agent.vision_seek import SeekVisualCueController

    box = {"source": "WORLD3D", "track_id": "WORLD3D:785",
           "kind": "unknown_object_candidate", "candidate_labels": ["quest_object_like"],
           "confidence": .45, "stable_frames": 2, "inspectable": False,
           "lifecycle": "ACTIVE", "observed_at": 1., "x": .55, "y": .48}
    state = {"monotonic_time": 1., "visual_candidates": [box]}
    generic = SeekVisualCueController()
    generic.begin({"purpose": "SEARCH_LOCAL_OBJECTIVE_AREA"}, state, 1.)
    assert generic._candidate(state) is None
    quest = SeekVisualCueController()
    quest.begin({"purpose": "SEARCH_LOCAL_OBJECT", "search_capability": "SEARCH_LOCAL_OBJECT",
                 "quest_id": 55639, "expected_tooltips": ["cocoons"]}, state, 1.)
    assessment = quest.observe(state, "frame1", 1.)
    assert assessment.reason == "derived_subject_probe_ready_for_hover_identification"
    commands = quest.command(state, "frame1", 1.)
    assert len(commands) == 1 and commands[0].kind == "HOVER"
