"""Measure World Map marker perception on recorded live captures.

Scans ``live-captures/*/manifest.jsonl`` of one or more agent output folders,
finds frames that show the full-screen World Map (canvas estimator), and
reports per frame:

* the heuristic detector's output (player arrow, gold-glyph and blue-area
  counts),
* the addon player position projected through the estimated canvas versus the
  detected arrow (projection error, px),
* addon quest state at that tick (active quests),
* the learned map detector's output when a model is selected.

``--bootstrap-dir`` additionally writes each map-open frame as a collector
sample (crop + facts + proposals) so it can enter the review pool.  Captures
are downscaled JPEGs; they are useful negatives / arrow examples but are
marked ``downscaled_capture`` in provenance.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from wowbot.vision.adapters.world_map import detect_world_map  # noqa: E402
from wowbot.vision.map_markers import (fast_world_map_hints, get_learned_map_detector,  # noqa: E402
                                       world_map_crop, world_map_proposals)
from wowbot.vision.models import MapPoint  # noqa: E402
from wowbot.vision.world_map_calibration import estimate_world_map_canvas  # noqa: E402


def iter_frames(outputs: list[Path]):
    for output in outputs:
        for manifest in sorted(output.glob("live-captures/*/manifest.jsonl")):
            for line in manifest.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                path = manifest.parent / row["frame"]
                if path.is_file():
                    yield output, manifest.parent.name, path, row.get("summary") or {}


def measure(outputs: list[Path], *, bootstrap_dir: Path | None = None,
            use_learned: bool = True) -> dict:
    learned = get_learned_map_detector("WORLD_MAP") if use_learned else None
    frames = []
    scanned = 0
    for output, segment, path, summary in iter_frames(outputs):
        scanned += 1
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None or estimate_world_map_canvas(bgr) is None:
            continue
        height, width = bgr.shape[:2]
        bgra = np.dstack([bgr, np.full((height, width), 255, np.uint8)])
        observation = detect_world_map(bgra.tobytes(), width, height)
        labels = Counter(label for marker in observation.markers
                         for label in (marker.candidate_labels or ("unlabelled",)))
        crop, canvas, estimated = world_map_crop(bgr, width, height)
        position = summary.get("position") or {}
        error = None
        if observation.player_marker and isinstance(position.get("x"), (int, float)):
            ex, ey = canvas.map_to_pixel(position["x"], position["y"])
            error = round(float(np.hypot(ex - observation.player_marker.x,
                                         ey - observation.player_marker.y)), 2)
        learned_labels: dict = {}
        if learned is not None:
            markers, player = learned.detect(
                np.ascontiguousarray(bgr[crop.top:crop.bottom, crop.left:crop.right]),
                offset=(crop.left, crop.top))
            learned_labels = dict(Counter(m.candidate_labels[0] for m in markers))
            learned_labels["player_arrow"] = int(player is not None)
        quests = summary.get("active_quests") or []
        record = {
            "frame": str(path.relative_to(output)), "segment": segment,
            "size": [width, height], "map_id": summary.get("map_id"),
            "decision": (summary.get("decision") or {}).get("skill"),
            "active_quests": len(quests),
            "player_arrow": ([observation.player_marker.x, observation.player_marker.y]
                             if observation.player_marker else None),
            "projection_error_px": error,
            "heuristic_marker_labels": dict(labels),
            "learned_marker_labels": learned_labels,
        }
        frames.append(record)
        if bootstrap_dir is not None:
            write_bootstrap_sample(bootstrap_dir, segment, path, bgr, crop, canvas, estimated,
                                   summary, observation.player_marker)
    errors = [f["projection_error_px"] for f in frames if f["projection_error_px"] is not None]
    totals = Counter()
    for frame in frames:
        totals.update(frame["heuristic_marker_labels"])
    return {
        "frames_scanned": scanned, "world_map_frames": len(frames),
        "frames_with_active_quests": sum(1 for f in frames if f["active_quests"]),
        "player_arrow_found": sum(1 for f in frames if f["player_arrow"]),
        "projection_error_px": ({"median": statistics.median(errors), "max": max(errors)}
                                if errors else None),
        "heuristic_marker_totals": dict(totals),
        "heuristic_markers_per_frame": (round(sum(totals.values()) / len(frames), 1)
                                        if frames else 0),
        "learned_model": "selected" if learned is not None else "none",
        "frames": frames,
    }


def write_bootstrap_sample(directory: Path, segment: str, path: Path, bgr, crop, canvas,
                           estimated: bool, summary: dict, player: MapPoint | None) -> None:
    surface_dir = directory / "world_map"
    (surface_dir / "images").mkdir(parents=True, exist_ok=True)
    (surface_dir / "meta").mkdir(parents=True, exist_ok=True)
    stem = f"cap-{segment}-{path.stem}"
    image = np.ascontiguousarray(bgr[crop.top:crop.bottom, crop.left:crop.right])
    cv2.imwrite(str(surface_dir / "images" / f"{stem}.png"), image)
    state = {"session_id": summary.get("session_id") or segment, "map_id": summary.get("map_id"),
             "position": summary.get("position"),
             "quests": [{"quest_id": q.get("quest_id"), "is_complete": q.get("is_complete")}
                        for q in summary.get("active_quests") or [] if isinstance(q, dict)]}
    _, areas = fast_world_map_hints(image)
    proposals, verification = world_map_proposals(
        crop=crop, canvas=canvas, canvas_estimated=estimated, state=state, player_pixel=player,
        heuristic_markers=[])
    for area in areas:  # crop-relative already
        left, top, right, bottom = area.bbox
        proposals.append({"class_id": 6, "class_name": "quest_area", "left": left, "top": top,
                          "right": right, "bottom": bottom, "confidence": .3,
                          "status": "PROPOSED", "source": "HEURISTIC_BLUE_REGION"})
    meta = {"sample_id": stem, "surface": "WORLD_MAP", "image": f"images/{stem}.png",
            "frame_size": {"width": bgr.shape[1], "height": bgr.shape[0]},
            "crop": crop.to_dict(), "verification": verification, "state": state,
            "proposals": proposals, "label_status": "UNLABELED_MAP_CROP",
            "provenance": {"collector": "LIVE_CAPTURE_BOOTSTRAP", "session_id": segment,
                           "downscaled_capture": True, "source_frame": str(path)}}
    (surface_dir / "meta" / f"{stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outputs", nargs="*", type=Path,
                        help="agent output folders (default: output/agent/pid-*)")
    parser.add_argument("--report", type=Path, help="write the full JSON report here")
    parser.add_argument("--bootstrap-dir", type=Path,
                        help="also write map-open frames as collector samples")
    parser.add_argument("--no-learned", action="store_true")
    args = parser.parse_args()
    outputs = args.outputs or sorted((ROOT / "output" / "agent").glob("pid-*"))
    report = measure(outputs, bootstrap_dir=args.bootstrap_dir, use_learned=not args.no_learned)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "frames"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
