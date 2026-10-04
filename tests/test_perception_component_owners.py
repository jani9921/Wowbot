from wowbot.agent.perception import PerceptionWorker
from wowbot.agent.perception_pipeline import PerceptionBatch, PerceptionPipeline
from wowbot.agent.visual_tracks import VisualTrackManager
from wowbot.vision.minimap_perception import MinimapResolver, MinimapTracker
from wowbot.vision.world3d.components import WorldCandidateDetector, WorldSceneExtractor
from wowbot.vision.world3d.models import PixelRect, WorldCandidate
from wowbot.vision.world3d.tracking import WorldCandidateTracker
from wowbot.vision.world_map_perception import (
    MapContextResolver, MapMouseoverResolver, WorldMapResolver, WorldMapStateDetector,
)


def test_perception_pipeline_selects_exactly_one_primary_surface():
    calls = []
    def processor(name):
        return lambda frame, at, geometry: calls.append(name) or [name]
    pipeline = PerceptionPipeline(world3d=processor("world3d"), minimap=processor("minimap"),
                                  world_map=processor("map"), ui=processor("ui"))
    frame = (b"", 1, 1)
    normal = pipeline.process_frame(frame, 1.0, {"visible": True})
    assert [batch.surface for batch in normal] == ["WORLD3D", "MINIMAP", "UI"]
    assert calls == ["world3d", "minimap", "ui"]
    calls.clear()
    mapped = pipeline.process_frame(frame, 2.0, {"visible": True, "world_map_open": True})
    assert [batch.surface for batch in mapped] == ["WORLD_MAP", "UI"]
    assert calls == ["map", "ui"]


def test_perception_pipeline_fuse_and_publish_are_explicit():
    batch = PerceptionBatch("WORLD3D", 3.0, ({"value": 1},))
    fused = PerceptionPipeline.fuse(batch, lambda item: {**item, "normalized": True})
    assert fused.observations[0]["normalized"] is True
    assert PerceptionPipeline.publish(fused, lambda value: value.surface) == "WORLD3D"


def test_world3d_stage_components_delegate_to_single_detector():
    calls = []
    class Detector:
        def process(self, raw, width, height, scene, **kwargs):
            calls.append((raw, width, height, scene, kwargs))
            return ("candidate",)
    frame = (bytes(640 * 480 * 4), 640, 480)
    scene = WorldSceneExtractor().extract(frame)
    result = WorldCandidateDetector(Detector()).detect(
        frame, scene, observed_at=4.0, ui_hints={"visible": True})
    assert result == ("candidate",)
    assert calls[0][3] is scene
    assert calls[0][4]["observed_at"] == 4.0


def test_world_candidate_tracker_exposes_lifecycle_contract_without_semantic_identity():
    tracker = WorldCandidateTracker(max_misses=0)
    candidate = WorldCandidate("unknown_subject_candidate", PixelRect(1, 2, 11, 22), .7, "shape")
    tracked = tracker.update([candidate], timestamp=1.0)[0]
    assert tracker.get_track(tracked.track_id)["kind"] == "unknown_subject_candidate"
    assert tracker.recent_tracks()[0]["observed_at"] == 1.0
    tracker.update([], timestamp=2.0)
    assert not tracker.recent_tracks()
    assert tracker.lost_tracks()[0]["lost_since"] == 2.0
    tracker.update([candidate], timestamp=3.0)
    tracker.invalidate_all("context_changed")
    assert not tracker.recent_tracks()


def test_minimap_tracker_reuses_shared_visual_track_authority():
    manager = VisualTrackManager()
    tracker = MinimapTracker(manager)
    payload = [{"kind": "unknown_minimap_marker", "x": .6, "y": .4,
                "confidence": .8, "candidate_labels": ["quest_badge_like"]}]
    first = tracker.update_markers(payload, 1.0)
    second = tracker.associate_across_frames(payload, 1.1)
    assert first[0]["track_id"] == second[0]["track_id"]
    assert manager.snapshot()[0]["track_id"] == second[0]["track_id"]


def test_minimap_resolver_treats_disappearance_as_uncertainty():
    resolver = MinimapResolver()
    markers = [{"confidence": .8, "candidate_labels": ["quest_badge_like"],
                "local_position": {"dx": 3, "dy": -4}}]
    cue = resolver.best_quest_cue(markers)
    assert resolver.local_direction(cue) == {"dx": 3, "dy": -4}
    assert resolver.cue_disappeared_interpretation(recent=True, context_changed=False) == "TEMPORARILY_OCCLUDED"


def test_world_map_components_keep_context_and_mouseover_provenance():
    state = WorldMapStateDetector.detect(
        geometry={"world_map_open": True, "ui_map_id": 1409}, observation=None)
    assert state["is_open"] is True
    context = MapContextResolver.resolve({}, {"ui_map_id": 1409, "instance_id": 2175})
    assert context["ui_map_id"] == 1409 and context["instance_id"] == 2175
    hover = MapMouseoverResolver.resolve({"name": "Jaina", "npc_id": 123, "junk": "drop"})
    assert hover == {"name": "Jaina", "npc_id": 123}


def test_world_map_resolver_contract_is_input_free_and_evidence_ranked():
    resolver = WorldMapResolver()
    assert resolver.open_map_request()["input_dispatched"] is False
    assert resolver.close_map_request()["input_dispatched"] is False
    markers = [{"id": "weak", "confidence": .3},
               {"id": "best", "confidence": .9, "parent_map_id": 1409}]
    assert resolver.find_quest_location(markers)["id"] == "best"
    assert resolver.find_turnin_location(markers)["id"] == "best"
    assert resolver.find_parent_zone_location(markers, 1409)["id"] == "best"
    assert resolver.resolve_wrong_zoom({"is_open": True, "parent_map": 947}) == {
        "operation": "STEP_TO_PARENT_MAP", "target_map": 947, "input_dispatched": False}
    assert resolver.resolve_wrong_zoom({"is_open": True})["max_steps"] == 5
    assert resolver.resolve_wrong_zoom({"is_open": False}) is None


def test_production_worker_wires_named_components_to_existing_authorities():
    worker = PerceptionWorker()
    try:
        assert worker.world_candidate_detector.detector is worker.world3d
        assert worker.minimap_tracker.track_manager is worker.visual_tracks
        assert worker.pipeline.process_world3d((b"", 1, 1), 1.0, {}) == []
    finally:
        worker.close()
