from __future__ import annotations

import numpy as np

from wowbot.agent.perception import PerceptionWorker
from wowbot.diagnostics.live_vision_monitor import (
    LiveVisionMonitor, _MonitorFrame, _configure_monitor_process,
)


def test_live_monitor_caps_diagnostic_opencv_resources(monkeypatch):
    monkeypatch.setenv("AIPC_LIVE_VISION_OPENCV_THREADS", "1")
    status = _configure_monitor_process()
    assert status["opencv_threads"] == 1
    assert status["opencl"] is False


def test_live_monitor_renders_agent_track_without_capturing_or_inference():
    width, height = 160, 100
    raw = np.zeros((height, width, 4), dtype=np.uint8)
    raw[:, :, 3] = 255
    item = _MonitorFrame(
        raw.tobytes(), width, height,
        {"tracks": [{
            "track_id": "WORLD3D:146",
            "bbox": {"left": 20, "top": 25, "right": 70, "bottom": 80},
            "appearance": {"learned_label_hypothesis": "creature_unit_like"},
            "confidence": .76,
            "lifecycle": "ACTIVE",
        }]},
        {}, "capture:test:1", 12.5, 1.0,
    )

    rendered = LiveVisionMonitor.render_frame(item, display_hz=10.0)

    assert rendered.shape == (height, width, 3)
    assert np.count_nonzero(rendered) > 0
    assert tuple(rendered[25, 20]) != (0, 0, 0)


def test_live_monitor_label_includes_track_id_and_keeps_self_identity():
    ordinary = {
        "track_id": "WORLD3D:146", "confidence": .255,
        "lifecycle": "ACTIVE",
        "appearance": {"learned_label_hypothesis": "humanoid_unit_like"},
    }
    own = {
        **ordinary, "track_id": "WORLD3D:3", "display_name": "Vbmnm",
        "self_player_avatar": True,
    }

    assert LiveVisionMonitor._track_label(ordinary) == (
        "WORLD3D:146 humanoid_unit_like 0.26 ACTIVE")
    assert LiveVisionMonitor._track_label(own) == (
        "WORLD3D:3 Vbmnm [SELF] 0.26 ACTIVE")


def test_live_monitor_process_starts_and_closes_without_blocking_agent():
    monitor = LiveVisionMonitor(maximum_hz=5.0)
    try:
        assert monitor._process.is_alive()
    finally:
        monitor.close()
    assert not monitor._process.is_alive()


def test_live_monitor_downscales_large_source_and_scales_track_overlay():
    width, height = 1920, 1080
    raw = np.zeros((height, width, 4), dtype=np.uint8)
    item = _MonitorFrame(
        raw.tobytes(), width, height,
        {"tracks": [{
            "bbox": {"left": 960, "top": 540, "right": 1200, "bottom": 900},
            "appearance": {"learned_label_hypothesis": "humanoid_unit_like"},
            "confidence": .8, "lifecycle": "ACTIVE",
        }]}, {}, "capture:test:large", 8.0, 1.0)

    rendered = LiveVisionMonitor.render_frame(
        item, max_width=960, max_height=540)

    assert rendered.shape == (540, 960, 3)
    # Source (960, 540) maps to the visible rectangle corner (480, 270).
    assert tuple(rendered[270, 480]) != (0, 0, 0)


def test_fast_overlay_names_only_unanchored_self_avatar_candidate():
    own = {"track_id": "own", "bbox": {"left": 20, "top": 25, "right": 70, "bottom": 80},
           "appearance": {"self_avatar_suppression_hint": True}}
    overlapping_npc = {
        **own, "track_id": "npc",
        "visual_relations": [{"type": "ABOVE", "belief": "SUPPORTED"}],
    }

    overlay = PerceptionWorker._fast_debug_overlay(
        [own, overlapping_npc], player_name="Vbmnm")

    assert overlay["tracks"][0]["display_name"] == "Vbmnm"
    assert overlay["tracks"][0]["self_player_avatar"] is True
    assert overlay["tracks"][1]["display_name"] is None
    assert overlay["tracks"][1]["self_player_avatar"] is False
