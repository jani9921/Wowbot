from __future__ import annotations

from pathlib import Path
import tempfile

from wowbot.vision.entity_memory import EntityMemory
from wowbot.vision.visual_signature import build_visual_signature
from wowbot.vision.world3d.models import PixelRect


def _frame(w=100, h=100):
    return bytes([80, 120, 180, 255] * (w*h))


def test_signature_is_stable_for_same_visual():
    rect = PixelRect(20, 20, 40, 60)
    a = build_visual_signature(_frame(), 100, 100, rect, kind="mob_candidate", relation="hostile")
    b = build_visual_signature(_frame(), 100, 100, rect, kind="mob_candidate", relation="hostile")
    assert a["signature_id"] == b["signature_id"]


def test_visual_identity_does_not_depend_on_detector_semantics():
    rect = PixelRect(20, 20, 40, 60)
    a = build_visual_signature(_frame(), 100, 100, rect, kind="mob_candidate", relation="hostile")
    b = build_visual_signature(_frame(), 100, 100, rect, kind="npc_candidate", relation="friendly")
    assert a["signature_id"] == b["signature_id"]
    assert a["detector_context"] != b["detector_context"]


def test_visual_identity_keeps_representation_spaces_separate():
    rect = PixelRect(20, 20, 40, 60)
    world = build_visual_signature(_frame(), 100, 100, rect, representation_space="WORLD3D")
    minimap = build_visual_signature(_frame(), 100, 100, rect, representation_space="MINIMAP")
    assert world["signature_id"] != minimap["signature_id"]


def test_memory_aggregates_same_signature():
    with tempfile.TemporaryDirectory() as d:
        mem = EntityMemory(Path(d) / "e.sqlite3")
        key = mem.record_mouseover({"npc_id": 123, "unit_type": "NPC", "guid": "Creature-1", "name": "Test"}, map_id=1, map_x=.2, map_y=.3, zone="X", observed_at=1)
        sig = {"version": 1, "signature_id": "abc"}
        mem.associate_visual(key, sig, observed_at=2)
        mem.associate_visual(key, sig, observed_at=3)
        rows = mem.visual_observations(key)
        assert rows[0]["seen_count"] == 2
        mem.close()


def test_visual_recognition_requires_repeated_confirmed_association():
    with tempfile.TemporaryDirectory() as d:
        mem = EntityMemory(Path(d) / "e.sqlite3")
        key = mem.record_mouseover({"npc_id": 123, "unit_type": "NPC", "guid": "Creature-1"},
                                   map_id=1, map_x=None, map_y=None, zone="X", observed_at=1)
        sig_a = build_visual_signature(_frame(), 100, 100, PixelRect(20, 20, 40, 60),
                                       kind="mob_candidate", relation="hostile")
        sig_b = build_visual_signature(_frame(), 100, 100, PixelRect(20, 20, 40, 60),
                                       kind="npc_candidate", relation="friendly")
        mem.associate_visual(key, sig_a, observed_at=2)
        assert mem.recognize_visual(sig_b) == []
        mem.associate_visual(key, sig_a, observed_at=3)
        mem.associate_visual(key, sig_a, observed_at=4)
        matches = mem.recognize_visual(sig_b)
        assert matches[0]["identity_key"] == "npc:123"
        assert matches[0]["status"] == "SUPPORTED" and matches[0]["seen_count"] == 3
        mem.close()


def test_visual_memory_age_gate_keeps_history_but_stops_reidentification():
    with tempfile.TemporaryDirectory() as d:
        mem = EntityMemory(Path(d) / "e.sqlite3")
        key = mem.record_mouseover({"npc_id": 123, "unit_type": "NPC"}, map_id=1,
                                   map_x=.2, map_y=.3, zone="X", observed_at=10)
        signature = {"version": 1, "signature_id": "aged"}
        for at in (10, 11, 12):
            mem.associate_visual(key, signature, observed_at=at)
        assert mem.recognize_visual(signature, as_of=20, max_age=20)
        assert mem.recognize_visual(signature, as_of=100, max_age=20) == []
        assert mem.visual_observations(key)[0]["seen_count"] == 3
        mem.close()


def test_repeated_visual_counterexamples_demote_without_one_shot_forgetting():
    with tempfile.TemporaryDirectory() as d:
        mem = EntityMemory(Path(d) / "e.sqlite3")
        key = mem.record_mouseover({"npc_id": 123, "unit_type": "NPC"}, map_id=1,
                                   map_x=None, map_y=None, zone="X", observed_at=1)
        signature = {"version": 1, "signature_id": "ambiguous"}
        for at in (2, 3, 4):
            mem.record_visual_outcome(key, signature, True, at)
        mem.record_visual_outcome(key, signature, False, 5)
        assert mem.recognize_visual(signature)[0]["failure_count"] == 1
        mem.record_visual_outcome(key, signature, False, 6)
        assert mem.recognize_visual(signature) == []
        observation = mem.visual_observations(key)[0]
        assert observation["seen_count"] == 3 and observation["failure_count"] == 2
        mem.close()
