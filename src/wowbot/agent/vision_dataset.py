"""Auto-labeled full-frame YOLO training data (detector-ready).

Whenever the addon confirms an identity via mouseover (name, npc_id,
attackable) at a known cursor position and a tracked World3D candidate sits
at that point (the same association threshold WorldModel uses), the *whole*
captured frame is saved with a YOLO label file.

User 2026-10-04: the former collector saved only the candidate's crop.  A
detector learns to *find* objects in a scene, so it needs full frames where
every object is boxed -- a crop has no background and no negatives, and a
frame with only the one confirmed box would teach the model that every other
unit is background.  Therefore each sample holds:

* the addon-confirmed box (``source: ADDON_CONFIRMED_MOUSEOVER``), and
* the runtime model's own other detections in that frame as pre-labels
  (``source: MODEL_PRELABEL``) -- to be reviewed (``review_status:
  NEEDS_REVIEW``) before training, e.g. with the annotation-assist models.

Layout under the dataset directory::

    images/<id>.jpg     full frame
    labels/<id>.txt     YOLO "class cx cy w h" (normalized), one line per box
    meta/<id>.json      boxes with source/confidence, label, tooltip/quest data
    data.yaml           class names of the runtime model
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .models import number

# Matches WorldModel._project_live_mouseover_anchor's own mouseover-to-track
# association threshold (world.py).
MAX_ASSOCIATION_DISTANCE = .09
# Class order of the runtime detector (world3d_units_3class_v10_e65).
CLASS_NAMES = ("creature_unit_like", "quest_object_outline_like", "overhead_symbol_like")
PRELABEL_MIN_CONFIDENCE = .25


def confirmed_mouseover_label(state: dict) -> dict | None:
    """The addon's own identity for the current mouseover, or None."""
    unit = state.get("mouseover") or {}
    guid, name = unit.get("guid"), unit.get("name")
    if not guid or not name or name == "Unknown until addon":
        return None
    return {"guid": guid, "name": name, "npc_id": unit.get("npc_id"),
            "attackable": unit.get("attackable", unit.get("is_attackable")),
            "dead": unit.get("dead", unit.get("is_dead"))}


def nearest_subject_candidate(candidates: list[dict], x: float, y: float) -> dict | None:
    """Closest tracked WORLD3D subject candidate to a screen point, or None
    if nothing is within MAX_ASSOCIATION_DISTANCE."""
    subjects = [item for item in candidates
                if "subject" in str(item.get("detector_kind") or item.get("kind") or "")
                and number(item.get("x")) is not None and number(item.get("y")) is not None]
    if not subjects:
        return None
    nearest = min(subjects, key=lambda item: math.hypot(float(item["x"])-x, float(item["y"])-y))
    if math.hypot(float(nearest["x"])-x, float(nearest["y"])-y) > MAX_ASSOCIATION_DISTANCE:
        return None
    return nearest


def _pixel_box(item: dict, width: int, height: int) -> tuple[int, int, int, int] | None:
    bbox = item.get("bbox") or {}
    if not all(isinstance(bbox.get(key), (int, float)) for key in ("left", "top", "right", "bottom")):
        return None
    left, top = max(0, int(bbox["left"])), max(0, int(bbox["top"]))
    right, bottom = min(width, int(bbox["right"])), min(height, int(bbox["bottom"]))
    if right-left < 4 or bottom-top < 4:
        return None
    return left, top, right, bottom


def _yolo_line(class_id: int, box: tuple[int, int, int, int], width: int, height: int) -> str:
    left, top, right, bottom = box
    return (f"{class_id} {(left+right)/2/width:.6f} {(top+bottom)/2/height:.6f} "
            f"{(right-left)/width:.6f} {(bottom-top)/height:.6f}")


def _model_class(item: dict) -> int | None:
    appearance = item.get("appearance") if isinstance(item.get("appearance"), dict) else {}
    hypothesis = str(appearance.get("learned_label_hypothesis") or "")
    return CLASS_NAMES.index(hypothesis) if hypothesis in CLASS_NAMES else None


class AutoLabeledExampleCollector:
    """Bounded local dataset of addon-confirmed, detector-ready frames."""

    def __init__(self, directory: Path | None, *, limit: int = 400, cooldown: float = 20.):
        self.directory = Path(directory) if directory else None
        self.limit = max(0, int(limit))
        self.cooldown = max(1., float(cooldown))
        self.last_seen: dict[str, float] = {}
        meta = self.directory / "meta" if self.directory else None
        self.saved = len(list(meta.glob("*.json"))) if meta and meta.is_dir() else 0

    def _write_data_yaml(self) -> None:
        path = self.directory / "data.yaml"
        if path.exists():
            return
        names = "\n".join(f"  {index}: {name}" for index, name in enumerate(CLASS_NAMES))
        path.write_text(f"path: .\ntrain: images\nval: images\nnames:\n{names}\n", encoding="utf-8")

    def consider(self, raw: bytes, width: int, height: int, state: dict, observed_at: float) -> int:
        if self.directory is None or self.saved >= self.limit or not raw:
            return 0
        label = confirmed_mouseover_label(state)
        if label is None:
            return 0
        cursor = state.get("cursor_position") or {}
        x, y = number(cursor.get("nx")), number(cursor.get("ny"))
        if x is None or y is None:
            return 0
        candidates = [item for item in state.get("visual_candidates") or () if isinstance(item, dict)]
        confirmed = nearest_subject_candidate(candidates, x, y)
        if confirmed is None:
            return 0
        track_key = str(confirmed.get("track_id") or f"{x:.3f}:{y:.3f}")
        if observed_at - self.last_seen.get(track_key, -1e9) < self.cooldown:
            return 0
        confirmed_box = _pixel_box(confirmed, width, height)
        if confirmed_box is None or confirmed_box[2]-confirmed_box[0] < 8 or confirmed_box[3]-confirmed_box[1] < 8:
            return 0

        boxes = [{"class_id": 0, "class_name": CLASS_NAMES[0], "box": confirmed_box,
                  "source": "ADDON_CONFIRMED_MOUSEOVER", "track_id": confirmed.get("track_id"),
                  "label": label}]
        for item in candidates:
            if item is confirmed or item.get("source") != "WORLD3D":
                continue
            if item.get("coasting") is True or (number(item.get("missing_frames")) or 0) > 0:
                continue        # a stale box would mislabel this frame
            class_id = _model_class(item)
            confidence = number(item.get("confidence")) or 0.
            box = _pixel_box(item, width, height)
            if class_id is None or box is None or confidence < PRELABEL_MIN_CONFIDENCE:
                continue
            boxes.append({"class_id": class_id, "class_name": CLASS_NAMES[class_id], "box": box,
                          "source": "MODEL_PRELABEL", "track_id": item.get("track_id"),
                          "confidence": round(confidence, 3)})

        from PIL import Image
        for folder in ("images", "labels", "meta"):
            (self.directory / folder).mkdir(parents=True, exist_ok=True)
        self._write_data_yaml()
        self.last_seen[track_key] = observed_at
        token = hashlib.sha256(f"{track_key}:{observed_at:.3f}".encode()).hexdigest()[:20]
        image = Image.frombytes("RGBA", (width, height), raw, "raw", "BGRA").convert("RGB")
        image.save(self.directory / "images" / f"{token}.jpg", quality=95)
        (self.directory / "labels" / f"{token}.txt").write_text(
            "\n".join(_yolo_line(entry["class_id"], entry["box"], width, height) for entry in boxes) + "\n",
            encoding="utf-8")
        mouse = state.get("mouseover") or {}
        metadata = {
            "sample_id": token, "observed_at": observed_at, "frame": {"width": width, "height": height},
            "label": label,
            "tooltip": mouse.get("tooltip"), "quest_related": mouse.get("quest_related"),
            "association_distance": round(math.hypot(float(confirmed["x"])-x, float(confirmed["y"])-y), 6),
            "boxes": [{**entry, "box": list(entry["box"])} for entry in boxes],
            "label_status": "AUTO_LABELED_PARTIAL", "review_status": "NEEDS_REVIEW",
            "label_source": "ADDON_CONFIRMED_MOUSEOVER+MODEL_PRELABEL",
        }
        (self.directory / "meta" / f"{token}.json").write_text(json.dumps(metadata), encoding="utf-8")
        self.saved += 1
        return 1

    def diagnostics(self) -> dict:
        return {"saved": self.saved, "limit": self.limit, "format": "YOLO_FULL_FRAME",
                "status": ("disabled" if self.directory is None else
                           "limit_reached" if self.saved >= self.limit else "ready")}
