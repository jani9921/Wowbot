from collections import deque
from concurrent.futures import Future
from types import SimpleNamespace

import numpy as np
import pytest

from wowbot.agent.models import Goal, Observation, Proposal, Outcome
from wowbot.agent.perception import PerceptionWorker
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.vision.world3d.candidates import _components
from wowbot.vision.world3d.models import PixelRect, WorldCandidate


def reference_components(mask, min_area=8, max_area=5000):
    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    result = []
    for y in range(h):
        for x0 in np.flatnonzero(mask[y] & ~visited[y]).tolist():
            if visited[y, x0]:
                continue
            queue = deque([(x0, y)])
            visited[y, x0] = True
            x1 = x2 = x0
            y1 = y2 = y
            area = 0
            while queue:
                x, yy = queue.popleft()
                area += 1
                x1, x2 = min(x1, x), max(x2, x)
                y1, y2 = min(y1, yy), max(y2, yy)
                for nx, ny in ((x+1, yy), (x-1, yy), (x, yy+1), (x, yy-1)):
                    if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((nx, ny))
            if min_area <= area <= max_area:
                result.append((x1, y1, x2+1, y2+1, area))
    return result


@pytest.mark.parametrize("density", [0., .02, .2, .5, .8, 1.])
def test_run_components_exact_flood_fill_parity(density):
    rng = np.random.default_rng(49)
    for _ in range(10):
        mask = rng.random((33, 49)) < density
        assert _components(mask, 1, 2000) == reference_components(mask, 1, 2000)
        assert _components(mask, 8, 40) == reference_components(mask, 8, 40)


def test_diagonal_pixels_not_joined_and_empty_mask():
    assert len(_components(np.eye(5, dtype=bool), 1)) == 5
    assert _components(np.zeros((0, 0), dtype=bool)) == []


def make_world(**extra):
    world = WorldModel()
    world.ingest(Observation.create({"session_id": "a", "timestamp": 1., "frame_id": "a1",
                                    "map_id": 1409, "player_present": True, **extra}, 1.))
    return world


def test_terrain_never_inspected_unknown_object_requires_stability():
    planner = Planner(SimpleNamespace(available=lambda *args: True))
    markers = [{"kind": k, "confidence": .9, "x": .4, "y": .5, "stable_frames": 1}
               for k in ("obstacle_candidate", "visual_candidate", "object_candidate")]
    goal = Goal.parse("Explore", 1.)
    assert not any(p.skill == "INSPECT" for p in planner.candidates(goal, make_world(visual_candidates=markers), 1.))
    markers[-1]["stable_frames"] = 3
    choices = planner.candidates(goal, make_world(visual_candidates=markers), 1.)
    assert [p.skill for p in choices] == ["INSPECT"]


def test_stable_unknown_minimap_candidate_can_be_mouseover_investigated():
    planner = Planner(SimpleNamespace(available=lambda *args: True))
    marker = {"kind": "minimap_candidate", "source": "MINIMAP_CV", "track_id": "MINIMAP_CV:7",
              "confidence": .72, "x": .8, "y": .8, "stable_frames": 3, "inspectable": True,
              "semantic_type": "UNKNOWN"}
    proposals = planner.inspections(make_world(visual_candidates=[marker]), 1., "MINIMAP_CV",
                                    Goal.parse("Questelj", 1.))
    assert proposals and proposals[0].skill == "INSPECT"
    assert proposals[0].parameters["semantic_type"] == "UNKNOWN"


def test_minimap_direction_hint_is_not_hovered():
    planner = Planner(SimpleNamespace(available=lambda *args: True))
    marker = {"kind": "quest_direction", "source": "MINIMAP_CV", "confidence": .95,
              "x": .5, "y": .9, "stable_frames": 5, "inspectable": False}
    assert planner.inspections(make_world(visual_candidates=[marker]), 1., "MINIMAP_CV",
                               Goal.parse("Questelj", 1.)) == []


def test_stable_selected_minimap_target_is_hovered_without_inventing_relation():
    planner = Planner(SimpleNamespace(available=lambda *args: True))
    marker = {"kind": "target", "source": "MINIMAP_CV", "track_id": "MINIMAP_CV:2",
              "confidence": .8, "x": .7, "y": .8, "stable_frames": 3, "inspectable": True,
              "semantic_type": "UNKNOWN", "appearance": {"color": "yellow", "symbol": None}}
    proposals = planner.inspections(make_world(visual_candidates=[marker]), 1., "MINIMAP_CV",
                                    Goal.parse("Questelj", 1.))
    assert proposals and proposals[0].skill == "INSPECT"
    assert proposals[0].parameters["semantic_type"] == "UNKNOWN"
    assert "relation" not in proposals[0].parameters


def test_stable_inspection_cooldown_survives_coordinate_and_confidence_jitter():
    planner = Planner(SimpleNamespace(available=lambda *args: True))
    marker = {"kind": "npc_candidate", "source": "WORLD3D", "track_id": "1:4", "confidence": .8, "x": .4, "y": .5}
    goal = Goal.parse("Explore", 1.)
    first = planner.candidates(goal, make_world(visual_candidates=[marker]), 1.)[0]
    planner.recent[first.key] = 30.
    marker.update(x=.408, confidence=.9)
    assert planner.candidates(goal, make_world(visual_candidates=[marker]), 2.)[0].skill == "WAIT"


def test_nameless_object_tracking_is_hypothesis_not_entity_fact():
    worker = PerceptionWorker()
    try:
        candidate = WorldCandidate("unknown_object_candidate", PixelRect(100, 100, 115, 120), .64)
        samples = [worker._candidates([candidate], 640, 480, 1.+i*.2)[0] for i in range(3)]
        assert len({s["track_id"] for s in samples}) == 1
        assert [s["inspectable"] for s in samples] == [False, False, True]
        assert all(s["confirmed"] is False for s in samples)
        worker._candidates([], 640, 480, 1.7)
        assert worker._candidates([candidate], 640, 480, 1.8)[0]["stable_frames"] == 1
    finally:
        worker.close()


def test_world_candidate_carries_nonsemantic_visual_signature_from_source_frame():
    worker = PerceptionWorker()
    try:
        image = np.zeros((80, 100, 4), dtype=np.uint8)
        image[20:35, 40:55, 2] = 220
        candidate = WorldCandidate("object_candidate", PixelRect(40, 20, 55, 35), .64)
        item = worker._candidates([candidate], 100, 80, 1., raw=image.tobytes())[0]
        assert item["bbox"]["coordinate_space"] == "CLIENT_PIXELS"
        assert item["visual_signature"]["signature_id"]
        assert "semantic_type" not in item["visual_signature"]
    finally:
        worker.close()


def test_cropped_minimap_matches_full_frame_coordinates():
    from wowbot.vision.adapters.minimap import detect_minimap
    from wowbot.vision.minimap_geometry import MinimapGeometry
    image = np.zeros((200, 300, 4), dtype=np.uint8)
    image[25:31, 276:278, :3] = (0, 150, 235)
    image[33:35, 276:278, :3] = (0, 150, 235)
    geom = MinimapGeometry()
    full = detect_minimap(image.tobytes(), 300, 200, geometry=geom)
    crop = PerceptionWorker._minimap((image.tobytes(), 300, 200), 1., {
        "visible": True, "center_x": geom.center_x_fraction, "center_y": geom.center_y_fraction,
        "radius_fraction": geom.radius_fraction})
    assert crop
    assert [(m.marker_type, m.position.x/300, 1-m.position.y/200) for m in full.markers] == [(m["kind"], m["x"], m["y"]) for m in crop]


class DeferredPool:
    def __init__(self): self.calls = []
    def submit(self, fn, *args):
        future = Future()
        self.calls.append((future, fn, args))
        return future
    def finish(self, index):
        future, fn, args = self.calls[index]
        future.set_result(fn(*args))


def test_minimap_completes_without_world_and_no_stale_queue(monkeypatch):
    worker = PerceptionWorker()
    worker.pool.shutdown()
    worker.pool = DeferredPool()
    monkeypatch.setattr(worker, "_minimap", lambda *args: [{"kind": "quest_giver"}])
    monkeypatch.setattr(worker, "_world", lambda *args: [])
    frame = (b"", 640, 480)
    worker.update(frame, 1., context="a")
    worker.pool.finish(1)
    assert worker.update(frame, 1.05, context="a") == [{"kind": "quest_giver"}]
    assert len(worker.pool.calls) == 2  # world still blocked, no backlog
    assert worker.update(frame, 1.06, context="b") == []
    worker.pool.finish(0)  # old world's completion cannot leak across session
    assert worker.update(frame, 1.07, context="b") == []


def test_completed_visual_track_survives_paged_telemetry_interval_but_not_freshness_boundary():
    worker = PerceptionWorker()
    try:
        worker.context = (None, None, True, "[('world_map_open', False)]")
        worker.lanes["world"].update({"items": [{"source": "WORLD3D", "track_id": "stable"}],
                                      "at": 1., "status": "ready"})
        assert worker.update(None, 3.8, context=None) == [
            {"source": "WORLD3D", "track_id": "stable"}]
        assert worker.ready_for_action(3.8)
        assert worker.update(None, 4.01, context=None) == []
        assert not worker.ready_for_action(4.01)
    finally:
        worker.close()


@pytest.mark.parametrize("after_mouse,expected", [(None, Outcome.PENDING), ({"guid": "new"}, Outcome.SUCCESS)])
def test_inspect_requires_new_identity_at_probe_not_cleared_mouseover(after_mouse, expected):
    world = make_world(mouseover=after_mouse, cursor_position={"nx": .4, "ny": .5})
    attempt = SimpleNamespace(observation_id="old", deadline=3., started_at=0.,
                              proposal=Proposal.make("INSPECT", "test", {"x": .4, "y": .5}),
                              baseline={"mouseover": {"guid": "old"}})
    assert SkillRegistry().verify(attempt, world, 1.)[0] == expected
