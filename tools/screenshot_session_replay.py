"""Rebuild a replayable JSONL from a saved live-capture screenshot segment.

Discovery 2026-09-14: the AIPC5 pixel-strip telemetry baked into every
live-capture screenshot survives JPEG compression -- decode_payload_from_bgra()
successfully recovered full payloads from several of this session's own
saved .jpg files (spot-checked across two different days/segments). This
means a whole recorded session's actual addon ground truth (target/quest/
health/actionbar/etc, whatever fits in each 1000-byte AIPC5 packet) can be
reconstructed from nothing but the screenshots -- no WoW client or addon
needed at replay time, only when the screenshots were originally captured.

This does NOT replay vision (World3D/minimap CV): decisions that depend on
`visual_candidates` (SEEK_VISUAL_CUE, VISUAL_APPROACH steering) will not see
fresh candidates this way, since nothing here re-runs the detector on each
frame. See tools/vision_replay.py for that piece; combining the two (feed
each frame's image through the detector too, merging visual_candidates into
the same state dict before writing it out) is a natural follow-up if a more
complete replay is needed later.

Usage:
    python tools/screenshot_session_replay.py <live-captures-segment-dir> [output.jsonl]

The output is consumable directly by wowbot.agent.runtime.replay(), e.g.:
    from pathlib import Path
    from wowbot.agent.runtime import replay
    replay(Path("output.jsonl"), Path("some/output/dir"))
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

import cv2

from src.adapters.pixel_bridge import decode_payload_from_bgra
from src.adapters.telemetry_packets import PacketAssembler


def frames_from_manifest(segment_dir: Path):
    """Yield (image_path, observed_monotonic) in chronological order."""
    manifest = segment_dir / "manifest.jsonl"
    if not manifest.exists():
        raise FileNotFoundError(f"no manifest.jsonl in {segment_dir}")
    entries = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        frame = row.get("frame")
        at = row.get("observed_monotonic")
        if frame and at is not None:
            entries.append((segment_dir / frame, float(at)))
    entries.sort(key=lambda pair: pair[1])
    return entries


def rebuild(segment_dir: Path) -> list[dict]:
    """Decode every frame's embedded AIPC5 payload and reassemble complete
    states via PacketAssembler, exactly as the live pixel-strip pipeline
    does. Returns a list of {"at": ..., "state": ...} dicts, ready to write
    as JSONL for wowbot.agent.runtime.replay()."""
    assembler = PacketAssembler()
    results = []
    decoded = skipped_no_strip = skipped_bad_packet = 0
    for image_path, at in frames_from_manifest(segment_dir):
        img = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
        if img is None:
            continue
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
        elif img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        height, width = img.shape[:2]
        payload = decode_payload_from_bgra(img.tobytes(), width, height)
        if payload is None:
            skipped_no_strip += 1
            continue
        try:
            state = assembler.feed(payload, at)
        except ValueError:
            skipped_bad_packet += 1
            continue
        decoded += 1
        if state is not None:
            results.append({"at": at, "state": state})
    print(f"frames with a decodable strip: {decoded}, no strip found: {skipped_no_strip}, "
          f"rejected packets: {skipped_bad_packet}, complete states assembled: {len(results)}",
          file=sys.stderr)
    return results


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    segment_dir = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else segment_dir / "replay.jsonl"
    results = rebuild(segment_dir)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {len(results)} observations to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
