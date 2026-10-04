"""Replay the unified World3D pipeline on saved live-capture frames.

The detector consumes BGRA, matching live Windows capture. The report keeps raw
diagnostics separate from the bounded candidate set actually handed downstream.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from PIL import Image, ImageDraw

from wowbot.vision.world3d.scene import build_scene_roi
from wowbot.vision.world3d.v3 import World3DPerceptionV3


COLORS = {
    "unknown_symbol_candidate": (255, 80, 255),
    "unknown_subject_probe": (0, 220, 80),
    "unknown_subject_candidate": (0, 200, 120),
    "unknown_object_candidate": (100, 180, 255),
    "unknown_scene_candidate": (120, 120, 120),
    "visual_candidate": (170, 170, 170),
}


def latest_capture_dir() -> Path | None:
    base = Path(__file__).parent.parent / "output" / "agent"
    choices = sorted(base.glob("*/live-captures/*"), key=lambda path: path.stat().st_mtime)
    return choices[-1] if choices else None


def annotate(source: Path, candidates: list[dict], output: Path) -> None:
    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    for item in candidates:
        box = item["bbox"]
        color = COLORS.get(item["kind"], (210, 210, 210))
        draw.rectangle((box["left"], box["top"], box["right"], box["bottom"]),
                       outline=color, width=2)
        draw.text((box["left"], max(0, box["top"]-13)),
                  f'{item["kind"][:19]} {item["confidence"]:.2f} s{item["stable_frames"]}',
                  fill=color)
    image.save(output, quality=88)


def run(capture_dir: Path, out_dir: Path, max_frames: int) -> None:
    manifest = capture_dir / "manifest.jsonl"
    if not manifest.exists():
        raise FileNotFoundError(f"Nincs manifest: {manifest}")
    entries = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    if max_frames:
        entries = entries[:max_frames]
    out_dir.mkdir(parents=True, exist_ok=True)
    world3d = World3DPerceptionV3()
    hits: Counter[int | str | None] = Counter()
    started = time.perf_counter()
    print(f"Capture: {capture_dir}\nOutput: {out_dir}")
    print(f"{'Frame':<22} {'kept':>5} {'raw':>5} {'overlap':>7} {'budget':>6} {'ms':>7}")
    for entry in entries:
        source = capture_dir / entry["frame"]
        image = Image.open(source).convert("RGBA")
        # Live capture and World3D candidate extraction use BGRA channel order.
        raw = image.tobytes("raw", "BGRA")
        at = float(entry.get("observed_monotonic", 0.0))
        before = time.perf_counter()
        output = world3d.process(raw, image.width, image.height,
                                 build_scene_roi(image.width, image.height), observed_at=at)
        elapsed_ms = (time.perf_counter()-before)*1000
        candidates = []
        for candidate in output:
            hits[candidate.track_id] += 1
            candidates.append({
                "track_id": candidate.track_id, "kind": candidate.kind,
                "confidence": round(candidate.confidence, 3),
                "stable_frames": hits[candidate.track_id],
                "bbox": {"left": candidate.rect.left, "top": candidate.rect.top,
                         "right": candidate.rect.right, "bottom": candidate.rect.bottom},
                "candidate_labels": list(candidate.candidate_labels),
                "evidence": candidate.evidence,
            })
        diagnostics = world3d.last_diagnostics.get("detector", {})
        print(f'{source.name:<22} {len(candidates):>5} '
              f'{diagnostics.get("pre_filter_candidates", len(candidates)):>5} '
              f'{diagnostics.get("suppressed_overlap", 0):>7} '
              f'{diagnostics.get("suppressed_budget", 0):>6} {elapsed_ms:>7.1f}')
        stem = source.stem
        annotate(source, candidates, out_dir / f"{stem}.jpg")
        (out_dir / f"{stem}.json").write_text(json.dumps({
            "frame": source.name, "at": at, "diagnostics": diagnostics,
            "candidates": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(entries)} frame, {time.perf_counter()-started:.1f} s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture_dir", nargs="?")
    parser.add_argument("--out")
    parser.add_argument("--max", type=int, default=0)
    args = parser.parse_args()
    capture = Path(args.capture_dir) if args.capture_dir else latest_capture_dir()
    if capture is None:
        raise SystemExit("Nincs capture mappa az output/agent alatt.")
    output = (Path(args.out) if args.out else
              Path(__file__).parent.parent / "output" / "vision_replay" / capture.name)
    run(capture, output, args.max)


if __name__ == "__main__":
    main()
