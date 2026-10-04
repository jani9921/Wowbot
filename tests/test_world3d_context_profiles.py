from wowbot.agent.perception import PerceptionWorker
from wowbot.vision.world3d.models import PixelRect, WorldCandidate
from wowbot.vision.world3d.ocr import TargetedOCR
from wowbot.vision.world3d.profiles import resolve_world3d_profile


def candidate(track_id, kind, labels=(), evidence=""):
    return WorldCandidate(kind, PixelRect(20+track_id*40, 20, 50+track_id*40, 90),
                          .7, evidence=evidence, track_id=track_id,
                          candidate_labels=tuple(labels))


def test_context_resolves_one_world3d_profile_without_new_pipeline_authority():
    assert resolve_world3d_profile({"is_in_combat": True}).name == "COMBAT"
    assert resolve_world3d_profile({"quest_search": True}).name == "QUEST_SEARCH"
    assert resolve_world3d_profile({"navigation_active": True}).name == "NAVIGATION"
    assert resolve_world3d_profile({}).name == "BALANCED"


def test_worker_schedule_uses_profile_tracker_rate_as_real_interval():
    worker = PerceptionWorker()
    try:
        combat = worker._dynamic_interval("world", {"is_in_combat": True})
        balanced = worker._dynamic_interval("world", {})
        assert combat == 1/40
        assert balanced == 1/40
    finally:
        worker.close()


def test_ocr_region_ranking_changes_by_context_and_remains_crop_only():
    ocr = TargetedOCR(max_regions=3)
    quest = candidate(1, "unknown_symbol_candidate", ("quest_badge_like",))
    combat = candidate(2, "unknown_subject_candidate", (), "nameplate-like cue")

    combat_regions = ocr.interest_regions(
        (quest, combat), 320, 240,
        {"world3d_profile": resolve_world3d_profile({"is_in_combat": True}).to_dict()})
    quest_regions = ocr.interest_regions(
        (quest, combat), 320, 240,
        {"world3d_profile": resolve_world3d_profile({"quest_search": True}).to_dict()})

    assert combat_regions[0][0] == "track:2"
    assert quest_regions[0][0] == "track:1"
    assert len(combat_regions) == 1  # profile budget, not full-screen OCR
    assert all(region.width < 320 or region.height < 240 for _, region, _ in quest_regions)
