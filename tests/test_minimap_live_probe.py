from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_probe():
    path = Path(__file__).resolve().parents[1] / "tools" / "minimap_live_probe.py"
    spec = importlib.util.spec_from_file_location("minimap_live_probe", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_marker_payload_schema():
    module = _load_probe()
    class Marker:
        marker_type = "target"
        position = type("P", (), {"x": 20, "y": 10})()
        confidence = 0.9
        marker_color = "yellow"
        relation = "neutral"
        symbol = None

    class Obs:
        markers = (Marker(),)
        def marker_relative(self, marker): return (2.0, -3.0)
        def marker_normalized(self, marker): return (0.1, -0.15)
        def marker_distance_px(self, marker): return 3.605551

    row = module.marker_payload(Obs())[0]
    assert row["type"] == "target"
    assert row["marker_color"] == "yellow"
    assert row["relation"] == "neutral"
    assert row["normalized_x"] == 0.1


def test_signature_changes_when_selected_target_changes():
    module = _load_probe()
    class Obs:
        width = 1600
        height = 829
        player_marker = type("P", (), {"x": 1474, "y": 144})()
        markers = ()
    a = module.signature(Obs())
    class Target:
        marker_type = "target"
        position = type("P", (), {"x": 1500, "y": 140})()
        marker_color = "yellow"
        relation = "neutral"
        symbol = None
    class Obs2(Obs):
        markers = (Target(),)
    assert module.signature(Obs2()) != a
