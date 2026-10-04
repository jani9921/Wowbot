import numpy as np

from wowbot.agent.perception import _minimap_marker_payload
from wowbot.vision.adapters.minimap import detect_minimap
from wowbot.vision.minimap_geometry import MinimapGeometry
from wowbot.vision.world3d.candidates import (
    _Component,
    _looks_symbol_like,
    detect_world_candidates,
)
from wowbot.vision.world3d.models import PixelRect, WorldSceneROI


def test_minimap_inner_salience_is_detected_without_colour_semantics():
    image = np.zeros((200, 200, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    # Magenta is deliberately outside the red/yellow/green target table.
    image[94:100, 128:134, :3] = (210, 25, 205)
    observed = detect_minimap(
        image.tobytes(), 200, 200, geometry=MinimapGeometry(.5, .5, .375)
    )
    candidates = [m for m in observed.markers if "salient_marker_like" in m.candidate_labels]
    assert candidates
    assert candidates[0].symbol is None and candidates[0].relation is None


def test_minimap_rim_ornaments_are_not_unknown_hover_targets():
    image = np.zeros((200, 200, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    for x, y in ((98, 24), (171, 98), (98, 171), (24, 98)):
        image[y:y + 5, x:x + 5, :3] = (20, 190, 245)
    observed = detect_minimap(
        image.tobytes(), 200, 200, geometry=MinimapGeometry(.5, .5, .375)
    )
    assert not any(m.marker_type == "minimap_candidate" for m in observed.markers)


def test_direction_markers_are_never_mouseover_targets():
    marker = type("Marker", (), {
        "marker_type": "quest_direction", "confidence": .9,
        "position": type("Point", (), {"x": 80, "y": 20})(),
        "bearing_degrees": 0, "marker_color": "yellow", "symbol": "arrow",
        "candidate_labels": ("gold_direction_like",), "evidence": (),
    })()
    assert _minimap_marker_payload(marker, 0, 0, 200, 200)["inspectable"] is False


def test_subject_shape_creates_entity_candidate_without_nameplate():
    image = np.zeros((180, 220, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    image[60:115, 95:120, :3] = (40, 190, 210)
    found = detect_world_candidates(
        image.tobytes(), 220, 180,
        WorldSceneROI(rect=PixelRect(0, 0, 220, 180)),
    )
    entity = next(c for c in found if c.kind == "unknown_subject_candidate")
    assert entity.relation is None
    assert "nameplate" not in entity.evidence


def test_reduced_ui_scale_nearly_square_overhead_badge_is_symbol_like_only():
    component = _Component(
        rect=PixelRect(549, 141, 572, 158), area=192, fill=.49,
        mean_saturation=62., mean_brightness=142.,
        mean_red=142., mean_green=130., mean_blue=80.,
    )
    assert _looks_symbol_like(component)

    distant = _Component(
        rect=PixelRect(561, 92, 573, 101), area=68, fill=.63,
        mean_saturation=87., mean_brightness=117.37,
        mean_red=117.37, mean_green=110., mean_blue=30.,
    )
    assert _looks_symbol_like(distant)

    tiny_low_chroma = _Component(
        rect=PixelRect(706, 286, 715, 294), area=59, fill=.82,
        mean_saturation=37., mean_brightness=140.,
        mean_red=140., mean_green=130., mean_blue=125.,
    )
    assert not _looks_symbol_like(tiny_low_chroma)
