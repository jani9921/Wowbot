"""Persistent identity for zero-information visual inspections.

This records only that inspecting an appearance/context was unproductive. It
does not classify the visual object or convert absence into semantic fact.
"""
from __future__ import annotations

import hashlib
from .models import canonical, number


def rejection_signature(marker: dict) -> str:
    visual = marker.get("visual_signature") or {}
    signature_id = visual.get("signature_id") if isinstance(visual, dict) else None
    appearance = visual.get("appearance") if isinstance(visual, dict) else None
    shape = visual.get("shape") if isinstance(visual, dict) else None
    if isinstance(appearance, dict) and isinstance(shape, dict):
        # Coarse, scale-tolerant appearance identity. Exact hashes changed too
        # easily with distance, lighting and a one-pixel bbox shift.
        def coarse(name):
            value = number(appearance.get(name))
            return int(value // 8) if value is not None else None
        aspect = number(shape.get("aspect"))
        x, y = number(marker.get("x")), number(marker.get("y"))
        raw = {
            "space": visual.get("representation_space"),
            "source": marker.get("source"),
            "visual_kind": marker.get("detector_kind") or marker.get("kind") or "UNKNOWN",
            "aspect_bin": round(aspect * 5) if aspect is not None else None,
            "appearance": [coarse(name) for name in (
                "brightness_bin", "saturation_bin", "red_bin",
                "green_bin", "blue_bin", "fill_bin")],
            # Until a calibrated screen-ground projection exists, locality is
            # deliberately screen-relative. This is less persistent across a
            # camera turn, but prevents a generic brown/green appearance from
            # suppressing every similar NPC/object on the entire map.
            "locality": [round(x * 8) if x is not None else None,
                         round(y * 8) if y is not None else None],
        }
    elif signature_id:
        raw = {"space": visual.get("representation_space"), "signature_id": signature_id}
    else:
        x, y = number(marker.get("x")), number(marker.get("y"))
        raw = {"source": marker.get("source"),
               "kind": marker.get("detector_kind") or marker.get("kind") or "UNKNOWN",
               "position_cell": [round(x*20) if x is not None else None,
                                 round(y*20) if y is not None else None]}
    return hashlib.sha256(canonical(raw).encode()).hexdigest()[:32]
