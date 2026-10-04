"""Quest-giver discovery without an active quest (user 2026-09-30).

"Keressen quest givert": prefer overhead quest cues, do not chase weak bare
bodies, and when the camera sweep at a spot is exhausted walk to another
walkable navmesh cell and sweep again.
"""
from types import SimpleNamespace

from wowbot.agent.active_perception import ActivePerception
from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.navigation_planning import NavigationProposalAdapter
from wowbot.agent.visual_search_planning import VisualSearchPlanningPolicy
from wowbot.agent.world import WorldModel
from wowbot.navigation.search_coverage import SearchCoveragePlanner


def _world(**overrides):
    state = {
        "session_id": "quest-giver-search", "frame_id": "f:1", "timestamp": 1.,
        "monotonic_time": 1., "map_id": 1609, "player_present": True,
        "is_in_combat": False, "health": 100, "max_health": 100,
        "target": None, "mouseover": None, "actionbar": [], "events": [],
        "event_sequence": 0, "active_quests": [], "confirmed_corpse_anchors": [],
    }
    state.update(overrides)
    value = WorldModel()
    value.ingest(Observation.create(state, 1.))
    return value


def _propose(world, *, camera_search_step=0):
    return VisualSearchPlanningPolicy().propose(
        [], world=world, goal=Goal.parse("Questelj", 1.), now=1.,
        target=world.query.target(), matching_objectives=(),
        active_perception=ActivePerception(), blocked_until={},
        world3d_probe_count=0, camera_search_step=camera_search_step,
        camera_search_next_at=0., camera_search_position=None).proposals


def _body(**overrides):
    track = {
        "source": "WORLD3D", "track_id": "WORLD3D:43", "detector_kind": "unknown_subject_candidate",
        "kind": "unknown_subject_candidate", "x": .62, "y": .40, "confidence": .6,
        "bbox_height_fraction": .06, "stable_frames": 4, "age": .3,
        "lifecycle": "ACTIVE", "candidate_labels": ["learned_subject_like"],
        "appearance": {}, "visual_relations": [],
    }
    track.update(overrides)
    return track


def _seek_targets(proposals):
    return [proposal.parameters.get("track_id") for proposal in proposals
            if proposal.skill == "SEEK_VISUAL_CUE" and proposal.parameters.get("track_id")]


def test_weak_bare_body_is_not_chased_without_a_quest():
    assert _seek_targets(_propose(_world(visual_candidates=[_body()]))) == []
    coasting = _body(stable_frames=30, age=2., coasting=True)
    assert _seek_targets(_propose(_world(visual_candidates=[coasting]))) == []


def test_established_bare_body_is_still_investigated():
    body = _body(stable_frames=14, age=1.2)
    assert _seek_targets(_propose(_world(visual_candidates=[body]))) == ["WORLD3D:43"]


def test_quest_badge_group_outranks_and_needs_no_long_history():
    body = _body(stable_frames=14, age=1.2)
    badge = _body(track_id="WORLD3D:52", x=.40, stable_frames=3,
                  appearance={"quest_badge_likeness": .8})
    proposals = _propose(_world(visual_candidates=[body, badge]))
    assert _seek_targets(proposals) == ["WORLD3D:52"]
    seek = next(p for p in proposals if p.skill == "SEEK_VISUAL_CUE")
    assert seek.priority == 87


def test_exhausted_sweep_proposes_navmesh_roam_instead_of_wait():
    world = _world(player_world_position={"instance_id": 2175, "x": 10., "y": 20., "z": 5.})
    proposals = _propose(world, camera_search_step=4)
    roam = [p for p in proposals if p.parameters.get("purpose") == "FIND_QUEST_GIVER_AREA"]
    assert len(roam) == 1 and roam[0].skill == "SEEK_VISUAL_CUE"
    # An active quest keeps its own objective-driven hierarchy.
    busy = _world(player_world_position={"instance_id": 2175, "x": 10., "y": 20., "z": 5.},
                  active_quests=[{"quest_id": 1, "title": "q", "objectives": []}])
    assert not any(p.parameters.get("purpose") == "FIND_QUEST_GIVER_AREA"
                   for p in _propose(busy, camera_search_step=4))


class _Navigation:
    """Real coverage planner, fake mmap surface (walkable unless x > 30)."""

    def __init__(self, *, walkable=lambda x, y: x <= 30.):
        self.coverage = SearchCoveragePlanner()
        self.walkable = walkable
        self.projected = []

    def permits(self, world, parameters, now): return True
    def waypoint(self, world, parameters): return parameters
    def begin_search_region(self, region_id, area): self.coverage.begin(region_id, area)

    def observe_search_region(self, region_id, state, now, *, target_detected):
        position = state.get("player_world_position") or {}
        self.coverage.observe(region_id, player_x=position.get("x"), player_y=position.get("y"),
                              target_detected=target_detected, now=now)

    def next_search_waypoint(self, region_id, state):
        position = state.get("player_world_position") or {}
        return self.coverage.next_waypoint(region_id, player_x=position.get("x"),
                                           player_y=position.get("y"))

    def mark_search_cell_visited(self, region_id, cell_id, now):
        self.coverage.mark_visited(region_id, cell_id, now)

    def search_region_completed(self, region_id):
        return self.coverage.completed(region_id)

    def walkable_point(self, instance_id, point, *, z_hint=None):
        self.projected.append((point["x"], point["y"]))
        if not self.walkable(point["x"], point["y"]):
            return None
        return {**point, "z": z_hint or 0., "instance_id": instance_id}


def _roam(adapter, x, y, now):
    proposal = Proposal.make("SEEK_VISUAL_CUE", "roam", {
        "source": "WORLD3D", "purpose": "FIND_QUEST_GIVER_AREA", "x": .5, "y": .45})
    world = SimpleNamespace(state={
        "player_world_position": {"instance_id": 2175, "x": x, "y": y, "z": 5.}})
    return adapter.adapt(proposal, [proposal], world, now)


def test_roam_moves_only_to_walkable_navmesh_cells():
    nav = _Navigation()
    result = _roam(NavigationProposalAdapter(nav), 10., 20., 1.)
    assert result.skill == "MOVE"
    assert result.parameters["purpose"] == "FIND_QUEST_GIVER_AREA"
    assert result.parameters["require_navmesh"] is True
    assert result.parameters["coordinate_space"] == "WORLD_YARDS"
    assert result.parameters["x"] <= 30.          # the off-mesh half is never a destination
    assert len(nav.projected) == 8


def test_roam_advances_after_arrival_and_skips_unreachable_cells():
    nav = _Navigation()
    adapter = NavigationProposalAdapter(nav)
    first = _roam(adapter, 10., 20., 1.)
    # Arrive at the first cell: the next MOVE targets a different cell.
    second = _roam(adapter, first.parameters["x"], first.parameters["y"], 5.)
    assert second.skill == "MOVE"
    assert (second.parameters["x"], second.parameters["y"]) != (
        first.parameters["x"], first.parameters["y"])
    # Never reaching a cell retires it after the timeout.
    third = _roam(adapter, first.parameters["x"], first.parameters["y"],
                  5. + NavigationProposalAdapter.ROAM_CELL_TIMEOUT_SECONDS + 1.)
    assert (third.parameters["x"], third.parameters["y"]) != (
        second.parameters["x"], second.parameters["y"])


def test_roam_without_navmesh_surface_keeps_the_in_place_sweep():
    nav = _Navigation(walkable=lambda x, y: False)
    result = _roam(NavigationProposalAdapter(nav), 10., 20., 1.)
    assert result.skill == "SEEK_VISUAL_CUE"


def test_roaming_move_yields_only_to_quest_symbol_evidence():
    attempt = SimpleNamespace(proposal=Proposal.make("MOVE", "roam", {
        "purpose": "FIND_QUEST_GIVER_AREA", "x": 38., "y": 20., "instance_id": 2175,
        "coordinate_space": "WORLD_YARDS", "require_navmesh": True}))
    state = {"monotonic_time": 10.,
             "player_world_position": {"instance_id": 2175, "x": 10., "y": 20.},
             "visual_candidates": [_body(stable_frames=40, confidence=.9, observed_at=10.)]}
    assert movement_visual_interrupt(attempt, state) is None
    state["visual_candidates"].append(_body(
        track_id="WORLD3D:52", stable_frames=5, confidence=.7, observed_at=10.,
        candidate_labels=["quest_marker_like"]))
    handoff = movement_visual_interrupt(attempt, state)
    assert handoff is not None and handoff["track_id"] == "WORLD3D:52"


def test_a_selected_other_player_does_not_block_the_quest_giver_search():
    """User 2026-10-01: a gnome player stayed selected and the agent only
    went to the quest giver after the user cleared the target by hand."""
    gnome = {"guid": "Player-1-ABC", "name": "Gnome", "is_player": True}
    badge = _body(track_id="WORLD3D:52", x=.40, stable_frames=3,
                  appearance={"quest_badge_likeness": .8})
    world = _world(target=gnome, visual_candidates=[badge])
    proposals = VisualSearchPlanningPolicy().propose(
        [], world=world, goal=Goal.parse("Questelj", 1.), now=1.,
        target=world.query.target(), matching_objectives=(),
        active_perception=ActivePerception(), blocked_until={},
        world3d_probe_count=0, camera_search_step=0,
        camera_search_next_at=0., camera_search_position=None).proposals
    assert _seek_targets(proposals) == ["WORLD3D:52"]
