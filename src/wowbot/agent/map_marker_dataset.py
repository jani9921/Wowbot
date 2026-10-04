"""Live World Map / minimap crop collector for the map-marker YOLO dataset.

While the World Map is open (or the minimap is visible) the collector saves
full-resolution crops of that surface together with the addon facts that
were true at the same tick: displayed map, player map position, quest log,
quest POIs, map mouseover tooltip.  Each crop gets *proposals* (player arrow,
projected quest POIs, tooltip-confirmed hover pins, heuristic blue areas) for
the reviewer; nothing is ever an accepted label until a human saves it
(tools/review_map_marker_annotations.py).

The agent step only performs cheap gating and hands the frame reference to a
single daemon writer thread (bounded queue, drop-on-full).  Cropping,
OpenCV hints and image encoding run there, so collection can neither block
the control loop nor hold the GIL for long (see gil-starvation history).
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import queue
import threading

from wowbot.vision.map_markers import (bgra_view, fast_world_map_hints, minimap_crop,
                                       minimap_proposals, world_map_crop,
                                       world_map_proposals)

from .models import number


_STATE_KEYS = ("session_id", "character_guid", "map_id", "displayed_map_id", "instance_id",
               "zone", "subzone", "position", "orientation", "world_map_open",
               "minimap_geometry", "quest_locations", "map_mouseover", "cursor_position",
               "ui_scale")


def _quest_facts(state: dict) -> list[dict]:
    result = []
    for quest in state.get("quests") or []:
        if not isinstance(quest, dict):
            continue
        result.append({key: quest.get(key) for key in
                       ("quest_id", "title", "is_complete", "is_campaign", "frequency",
                        "is_daily", "is_weekly", "waypoint", "level")
                       if quest.get(key) is not None})
    return result


def state_snapshot(state: dict) -> dict:
    """JSON-safe copy of the facts needed for labelling and later audits."""
    snapshot = {key: state.get(key) for key in _STATE_KEYS if state.get(key) is not None}
    snapshot["quests"] = _quest_facts(state)
    return json.loads(json.dumps(snapshot, default=str))


def facts_signature(snapshot: dict) -> str:
    mouseover = snapshot.get("map_mouseover") or {}
    cursor = snapshot.get("cursor_position") or {}
    payload = {
        "map": snapshot.get("displayed_map_id") or snapshot.get("map_id"),
        "quests": sorted((str(q.get("quest_id")), bool(q.get("is_complete")))
                         for q in snapshot.get("quests") or []),
        "pois": sorted((str(p.get("quest_id")), round(float(p.get("x") or 0), 3),
                        round(float(p.get("y") or 0), 3))
                       for p in snapshot.get("quest_locations") or [] if isinstance(p, dict)),
        "tooltip": mouseover.get("tooltip"),
        "cursor": (round(float(cursor.get("nx") or 0), 2), round(float(cursor.get("ny") or 0), 2)),
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class MapMarkerCropCollector:
    """Bounded, deduplicated, background map/minimap crop dataset."""

    def __init__(self, directory: Path | None, *, world_map_interval: float = 1.5,
                 minimap_interval: float = 4., world_map_limit: int = 1200,
                 minimap_limit: int = 3000, background: bool = True,
                 change_threshold: float = 1.5) -> None:
        self.directory = Path(directory) if directory else None
        self.intervals = {"WORLD_MAP": max(.2, float(world_map_interval)),
                          "MINIMAP": max(.2, float(minimap_interval))}
        self.limits = {"WORLD_MAP": max(0, int(world_map_limit)),
                       "MINIMAP": max(0, int(minimap_limit))}
        self.change_threshold = float(change_threshold)
        self.saved = {surface: self._existing(surface) for surface in self.limits}
        self.next_due = {surface: -1e18 for surface in self.limits}
        self.dropped = 0
        self.skipped_duplicates = 0
        self.errors = 0
        self.last_error: str | None = None
        self._last_thumb: dict[str, object] = {}
        self._last_facts: dict[str, str] = {}
        self._queue: queue.Queue | None = None
        if background and self.directory is not None:
            self._queue = queue.Queue(maxsize=3)
            threading.Thread(target=self._worker, name="aipc-map-dataset", daemon=True).start()

    def _surface_dir(self, surface: str) -> Path:
        return self.directory / surface.lower()

    def _existing(self, surface: str) -> int:
        if self.directory is None:
            return 0
        meta = self._surface_dir(surface) / "meta"
        return len(list(meta.glob("*.json"))) if meta.is_dir() else 0

    def consider(self, raw: bytes, width: int, height: int, state: dict,
                 observed_at: float) -> int:
        """Agent-step hook: cheap gating only.  Returns jobs enqueued."""
        if self.directory is None or not raw or len(raw) != width * height * 4:
            return 0
        surface = None
        if state.get("world_map_open"):
            surface = "WORLD_MAP"
        elif (state.get("minimap_geometry") or {}).get("visible"):
            surface = "MINIMAP"
        if surface is None or self.saved[surface] >= self.limits[surface]:
            return 0
        if observed_at < self.next_due[surface]:
            return 0
        self.next_due[surface] = observed_at + self.intervals[surface]
        job = (surface, raw, int(width), int(height), state_snapshot(state), float(observed_at))
        if self._queue is None:
            return self._process(job)
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            self.dropped += 1
            return 0
        return 1

    def _worker(self) -> None:
        while True:
            job = self._queue.get()
            try:
                self._process(job)
            except Exception as error:  # never let the dataset kill the agent
                self.errors += 1
                self.last_error = f"{type(error).__name__}:{error}"

    def _process(self, job) -> int:
        import cv2
        import numpy as np
        surface, raw, width, height, snapshot, observed_at = job
        pixels = bgra_view(raw, width, height)
        verification: dict = {}
        if surface == "WORLD_MAP":
            crop, canvas, estimated = world_map_crop(pixels, width, height)
            bgr = np.ascontiguousarray(pixels[crop.top:crop.bottom, crop.left:crop.right, :3])
            player, areas = fast_world_map_hints(bgr)
            # Hints are crop-relative; proposals expect client pixels.
            from wowbot.vision.models import MapPoint, MarkerObservation
            player_px = MapPoint(player.x + crop.left, player.y + crop.top) if player else None
            areas_px = [MarkerObservation(a.marker_type, a.position, a.confidence,
                                          candidate_labels=a.candidate_labels,
                                          evidence=a.evidence,
                                          bbox=(a.bbox[0] + crop.left, a.bbox[1] + crop.top,
                                                a.bbox[2] + crop.left, a.bbox[3] + crop.top))
                        for a in areas]
            cursor = snapshot.get("cursor_position") or {}
            nx, ny = number(cursor.get("nx")), number(cursor.get("ny"))
            cursor_px = (nx * width, (1. - ny) * height) if nx is not None and ny is not None else None
            proposals, verification = world_map_proposals(
                crop=crop, canvas=canvas, canvas_estimated=estimated, state=snapshot,
                player_pixel=player_px, heuristic_markers=areas_px, cursor_pixel=cursor_px)
            verification["canvas"] = {"left": canvas.left_px, "top": canvas.top_px,
                                      "right": canvas.right_px, "bottom": canvas.bottom_px}
            suffix, params = ".jpg", [cv2.IMWRITE_JPEG_QUALITY, 95]
        else:
            crop = minimap_crop(snapshot.get("minimap_geometry"), width, height)
            if crop is None:
                return 0
            bgr = np.ascontiguousarray(pixels[crop.top:crop.bottom, crop.left:crop.right, :3])
            from wowbot.vision.adapters.minimap import detect_minimap
            from wowbot.vision.minimap_geometry import MinimapGeometry
            geometry = snapshot["minimap_geometry"]
            cx = float(geometry["center_x"]) * width - crop.left
            cy = float(geometry["center_y"]) * height - crop.top
            radius = float(geometry["radius_fraction"]) * height
            local = MinimapGeometry(cx / crop.width, cy / crop.height, radius / crop.height)
            crop_bgra = np.ascontiguousarray(pixels[crop.top:crop.bottom, crop.left:crop.right])
            observation = detect_minimap(crop_bgra.tobytes(), crop.width, crop.height,
                                         geometry=local)
            proposals = minimap_proposals(crop=crop, markers=observation.markers)
            verification = {"minimap_center_px": [round(cx, 1), round(cy, 1)],
                            "minimap_radius_px": round(radius, 1)}
            suffix, params = ".png", [cv2.IMWRITE_PNG_COMPRESSION, 3]
        if crop.width < 16 or crop.height < 16:
            return 0
        thumb = cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (48, 32),
                           interpolation=cv2.INTER_AREA).astype(np.float32)
        signature = facts_signature(snapshot)
        previous = self._last_thumb.get(surface)
        if (previous is not None and self._last_facts.get(surface) == signature
                and float(np.abs(thumb - previous).mean()) < self.change_threshold):
            self.skipped_duplicates += 1
            return 0
        directory = self._surface_dir(surface)
        (directory / "images").mkdir(parents=True, exist_ok=True)
        (directory / "meta").mkdir(parents=True, exist_ok=True)
        token = hashlib.sha256(
            f"{surface}:{snapshot.get('session_id')}:{observed_at:.3f}".encode()).hexdigest()[:20]
        image_name = f"{token}{suffix}"
        ok, encoded = cv2.imencode(suffix, bgr, params)
        if not ok:
            return 0
        (directory / "images" / image_name).write_bytes(encoded.tobytes())
        metadata = {
            "sample_id": token, "surface": surface, "image": f"images/{image_name}",
            "observed_at": observed_at,
            "saved_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "frame_size": {"width": width, "height": height},
            "crop": crop.to_dict(), "verification": verification,
            "state": snapshot, "proposals": proposals,
            "label_status": "UNLABELED_MAP_CROP",
            "provenance": {"collector": "MAP_MARKER_CROP_V1",
                           "session_id": snapshot.get("session_id")},
        }
        (directory / "meta" / f"{token}.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=1), encoding="utf-8")
        self._last_thumb[surface] = thumb
        self._last_facts[surface] = signature
        self.saved[surface] += 1
        return 1

    def diagnostics(self) -> dict:
        return {"saved": dict(self.saved), "limits": dict(self.limits),
                "dropped": self.dropped, "skipped_duplicates": self.skipped_duplicates,
                "errors": self.errors, "last_error": self.last_error,
                "status": ("disabled" if self.directory is None else
                           "limit_reached" if all(self.saved[s] >= self.limits[s]
                                                  for s in self.limits) else "ready")}
