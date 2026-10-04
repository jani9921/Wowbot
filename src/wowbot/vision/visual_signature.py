from __future__ import annotations

import hashlib
import json
import math
from typing import Any

try:
    from src.adapters.numpy_runtime import np
except ModuleNotFoundError:
    from adapters.numpy_runtime import np
try:
    import cv2
except ImportError:  # pragma: no cover - numpy fallback keeps identical bins
    cv2 = None


def appearance_embedding(crop_bgr) -> list[float]:
    """37-d appearance vector of a BGR crop (unit length).

    User 2026-10-04: "if this shape had to be killed, inspect similar ones".
    Hue histogram weighted by saturation (12), saturation (4) and value (4)
    histograms, a 4x4 brightness layout (16, zero-mean) and log aspect (1).
    Coarse on purpose: the same creature model under different light and
    distance should stay close; a corpse, a player or a different species
    should not.
    """
    h, w = crop_bgr.shape[:2]
    if h < 2 or w < 2:
        return []
    if cv2 is not None:
        small = cv2.resize(np.ascontiguousarray(crop_bgr), (16, 16), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
        hue, sat, val = hsv[:, 0]/180., hsv[:, 1]/255., hsv[:, 2]/255.
    else:
        ys = (np.arange(16)*h//16).clip(0, h-1)
        xs = (np.arange(16)*w//16).clip(0, w-1)
        small = crop_bgr[ys][:, xs].astype(np.float32)/255.
        b, g, r = small[..., 0].ravel(), small[..., 1].ravel(), small[..., 2].ravel()
        mx, mn = np.maximum(np.maximum(r, g), b), np.minimum(np.minimum(r, g), b)
        delta = np.where(mx-mn == 0, 1e-6, mx-mn)
        hue = np.where(mx == r, ((g-b)/delta) % 6, np.where(mx == g, (b-r)/delta+2, (r-g)/delta+4))/6.
        sat, val = np.where(mx == 0, 0, (mx-mn)/np.maximum(mx, 1e-6)), mx
        gray = (0.299*small[..., 2]+0.587*small[..., 1]+0.114*small[..., 0])*255.
    weight = sat*val
    hue_hist = np.bincount(np.minimum((hue*12).astype(int), 11), weights=weight, minlength=12)
    sat_hist = np.bincount(np.minimum((sat*4).astype(int), 3), minlength=4).astype(np.float64)
    val_hist = np.bincount(np.minimum((val*4).astype(int), 3), minlength=4).astype(np.float64)
    grid = gray.reshape(4, 4, 4, 4).mean(axis=(1, 3)).ravel()
    grid = grid-grid.mean()
    parts = [hue_hist/max(1e-6, hue_hist.sum()), sat_hist/max(1e-6, sat_hist.sum()),
             val_hist/max(1e-6, val_hist.sum()), grid/max(1e-6, float(np.linalg.norm(grid)))*.5,
             np.array([math.log(max(.1, w/max(h, 1)))*.5])]
    vector = np.concatenate([np.asarray(part, dtype=np.float64) for part in parts])
    norm = float(np.linalg.norm(vector))
    return [round(float(value)/norm, 4) for value in vector] if norm > 0 else []


def build_visual_signature(raw_bgra: bytes, width: int, height: int, rect: Any, *, kind: str | None = None,
                           relation: str | None = None, class_name: str | None = None,
                           representation_space: str | None = None) -> dict[str, Any]:
    """Build a compact, position-independent visual signature for one Vision candidate.

    This is deliberately not semantic recognition. It records coarse visual evidence
    that can later be learned against an addon-confirmed NPC identity.
    """
    arr = np.frombuffer(raw_bgra, dtype=np.uint8).reshape((height, width, 4))[:, :, :3]
    left = max(0, int(rect.left)); top = max(0, int(rect.top))
    right = min(width, int(rect.right)); bottom = min(height, int(rect.bottom))
    if right <= left or bottom <= top:
        return {"version": 2, "invalid": True,
                "detector_context": {"kind": kind, "relation": relation, "class_name": class_name}}

    # Live 2026-09-30 this was ~65 % of the perception-pump thread: converting
    # every crop to float32 and reducing per pixel on each detector refresh.
    # The same statistics come from uint8 reductions: channel means directly,
    # gray as the linear combination of those means, saturation from the
    # per-pixel max/min of the original bytes.
    crop = arr[top:bottom, left:right]
    h, w = crop.shape[:2]
    pixels = h * w
    if cv2 is not None:
        # OpenCV reduces in C with double accumulation and releases the GIL,
        # so this no longer stalls the agent thread while it runs.
        blue, green, red = cv2.split(np.ascontiguousarray(crop))
        b_mean, g_mean, r_mean = cv2.mean(blue)[0], cv2.mean(green)[0], cv2.mean(red)[0]
        mx = cv2.max(cv2.max(blue, green), red)
        sat_mean = cv2.mean(cv2.subtract(mx, cv2.min(cv2.min(blue, green), red)))[0]
    else:
        sums = crop.reshape(-1, 3).sum(axis=0, dtype=np.int64)
        b_mean, g_mean, r_mean = (float(value) / pixels for value in sums)
        mx = crop.max(axis=2)
        sat_mean = float(np.subtract(mx, crop.min(axis=2), dtype=np.int16).sum(dtype=np.int64)) / pixels
    gray_mean = 0.299 * r_mean + 0.587 * g_mean + 0.114 * b_mean

    # Quantized measurements suppress frame-to-frame noise while retaining shape/color cues.
    aspect = round((w / max(h, 1)), 2)
    fill = round(float(np.count_nonzero(mx > 90)) / pixels, 2)
    signature = {
        "version": 2,
        "representation_space": representation_space or "WORLD3D",
        "shape": {"w_bin": min(31, w // 4), "h_bin": min(31, h // 4), "aspect": aspect},
        "appearance": {
            "brightness_bin": min(31, int(gray_mean / 8)),
            "saturation_bin": min(31, int(sat_mean / 8)),
            "red_bin": min(31, int(r_mean / 8)),
            "green_bin": min(31, int(g_mean / 8)),
            "blue_bin": min(31, int(b_mean / 8)),
            "fill_bin": min(31, int(fill * 31)),
        },
    }
    encoded = json.dumps(signature, sort_keys=True, separators=(",", ":")).encode()
    signature["signature_id"] = hashlib.sha1(encoded).hexdigest()[:16]
    # Not part of the hash: a compact appearance vector for per-quest visual
    # prototypes (visual_prototypes.py).
    signature["embedding"] = appearance_embedding(crop)
    # These fields explain which detector produced the crop. They are not part
    # of the appearance hash and cannot change visual identity.
    signature["detector_context"] = {"kind": kind, "relation": relation, "class_name": class_name}
    return signature
