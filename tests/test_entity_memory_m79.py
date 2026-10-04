from pathlib import Path
import tempfile

from wowbot.vision.entity_memory import EntityMemory


def test_mouseover_entity_persists_identity_and_locations():
    with tempfile.TemporaryDirectory() as tmp:
        memory = EntityMemory(Path(tmp) / "entities.sqlite3")
        entity = {"unit_type": "NPC", "npc_id": 123456, "guid": "Creature-0-1-2-123456-ABC", "name": "Test Ogre"}
        key = memory.record_mouseover(entity, map_id=1409, map_x=0.41, map_y=0.62, zone="Test Zone", observed_at=100.0)
        assert key == "npc:123456"
        memory.record_mouseover(entity, map_id=1409, map_x=0.415, map_y=0.625, zone="Test Zone", observed_at=110.0)
        summary = memory.summary(key)
        assert summary["seen_count"] == 2
        assert summary["npc_id"] == 123456
        assert len(summary["known_locations"]) == 1
        assert summary["known_locations"][0]["seen_count"] == 2
        memory.close()


def test_non_unit_without_identity_is_not_recorded():
    with tempfile.TemporaryDirectory() as tmp:
        memory = EntityMemory(Path(tmp) / "entities.sqlite3")
        assert memory.record_mouseover({"unit_type": "OBJECT", "name": "Rock"}, map_id=1409, map_x=0.2, map_y=0.3, zone="Z") is None
        memory.close()


def test_persistent_location_clusters_do_not_merge_phase_instance_or_quest_context():
    with tempfile.TemporaryDirectory() as tmp:
        memory = EntityMemory(Path(tmp) / "entities.sqlite3")
        entity = {"unit_type": "NPC", "npc_id": 77, "guid": "Creature-77", "name": "Guide"}
        memory.record_mouseover(entity, map_id=1409, map_x=.4, map_y=.5, zone="Z",
                                phase="p1", instance_id="i1", quest_revision="q1", observed_at=1)
        memory.record_mouseover(entity, map_id=1409, map_x=.405, map_y=.505, zone="Z",
                                phase="p1", instance_id="i1", quest_revision="q1", observed_at=2)
        memory.record_mouseover(entity, map_id=1409, map_x=.4, map_y=.5, zone="Z",
                                phase="p2", instance_id="i1", quest_revision="q1", observed_at=3)
        memory.record_mouseover(entity, map_id=1409, map_x=.4, map_y=.5, zone="Z",
                                phase="p1", instance_id="i2", quest_revision="q1", observed_at=4)
        memory.record_mouseover(entity, map_id=1409, map_x=.4, map_y=.5, zone="Z",
                                phase="p1", instance_id="i1", quest_revision="q2", observed_at=5)
        locations = memory.locations("npc:77")
        assert len(locations) == 4
        assert sorted(location["seen_count"] for location in locations) == [1, 1, 1, 2]
        contexts = {(location["phase"], location["instance_id"], location["context"])
                    for location in locations}
        assert len(contexts) == 4
        memory.close()


def _world3d_signature(*, brightness: int, red: int, green: int, blue: int, aspect: float = .50):
    return {
        "version": 2,
        "representation_space": "WORLD3D",
        "shape": {"aspect": aspect, "w_bin": 8, "h_bin": 16},
        "appearance": {
            "brightness_bin": brightness, "saturation_bin": 3, "red_bin": red,
            "green_bin": green, "blue_bin": blue, "fill_bin": 12,
        },
    }


def test_two_independent_exact_hover_views_can_offer_only_a_visual_candidate():
    with tempfile.TemporaryDirectory() as tmp:
        memory = EntityMemory(Path(tmp) / "entities.sqlite3")
        identity = "npc:150228"
        # These stand for two independently cursor/GUID-confirmed hovers,
        # not two detector frames of one unverified box.
        memory.associate_visual(identity, _world3d_signature(brightness=9, red=9, green=9, blue=9), 1)
        memory.associate_visual(identity, _world3d_signature(brightness=10, red=10, green=10, blue=10), 2)
        matches = memory.recognize_visual(
            _world3d_signature(brightness=9, red=9, green=9, blue=9), as_of=3, max_age=60)
        assert len(matches) == 1
        assert matches[0]["identity_key"] == identity
        assert matches[0]["status"] == "CANDIDATE"
        assert matches[0]["match_method"] == "MULTI_EXAMPLE_VISUAL_REIDENTIFICATION"
        assert matches[0]["independent_example_count"] == 2
        memory.close()


def test_new_multiview_candidate_is_not_hidden_by_an_older_supported_template():
    with tempfile.TemporaryDirectory() as tmp:
        memory = EntityMemory(Path(tmp) / "entities.sqlite3")
        old = _world3d_signature(brightness=11, red=11, green=11, blue=11)
        for at in (1, 2, 3):
            memory.associate_visual("npc:old", old, at)
        current = _world3d_signature(brightness=9, red=9, green=9, blue=9)
        memory.associate_visual("npc:new", current, 4)
        memory.associate_visual("npc:new", _world3d_signature(
            brightness=10, red=10, green=10, blue=10), 5)
        matches = memory.recognize_visual(current, as_of=6, max_age=60)
        assert matches[0]["identity_key"] == "npc:new"
        assert matches[0]["match_method"] == "MULTI_EXAMPLE_VISUAL_REIDENTIFICATION"
        assert {match["identity_key"] for match in matches} == {"npc:old", "npc:new"}
        memory.close()


def test_two_labelled_views_support_one_strong_match_when_camera_scale_changes():
    with tempfile.TemporaryDirectory() as tmp:
        memory = EntityMemory(Path(tmp) / "entities.sqlite3")
        close = _world3d_signature(brightness=9, red=9, green=9, blue=9, aspect=.50)
        distant = _world3d_signature(brightness=22, red=22, green=22, blue=22, aspect=.86)
        memory.associate_visual("npc:150228", close, 1)
        memory.associate_visual("npc:150228", distant, 2)
        matches = memory.recognize_visual(close, as_of=3, max_age=60)
        assert matches[0]["identity_key"] == "npc:150228"
        assert matches[0]["status"] == "CANDIDATE"
        assert matches[0]["independent_example_count"] == 2
        assert matches[0]["matched_example_count"] == 1
        memory.close()


def test_multiview_recognition_rejects_broad_visual_resemblance():
    with tempfile.TemporaryDirectory() as tmp:
        memory = EntityMemory(Path(tmp) / "entities.sqlite3")
        memory.associate_visual("npc:150228", _world3d_signature(
            brightness=9, red=9, green=9, blue=9), 1)
        memory.associate_visual("npc:150228", _world3d_signature(
            brightness=10, red=10, green=10, blue=10), 2)
        # Similar enough to be a broad colour/shape resemblance under the
        # old threshold, but not safe enough to identify without mouseover.
        weak = _world3d_signature(brightness=12, red=12, green=12, blue=12)
        assert memory.recognize_visual(weak, as_of=3, max_age=60) == []
        memory.close()

