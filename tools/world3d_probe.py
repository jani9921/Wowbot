from __future__ import annotations

import argparse
import json
import logging  # preload stdlib logging before project src/ is added to sys.path
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for entry in (ROOT, SRC):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from src.adapters.pixel_bridge import capture_hwnd_bgra, decode_payload_from_bgra, payload_to_state  # noqa: E402
from tools.wow_window import find_best_wow_window  # noqa: E402
from wowbot.vision.fusion import PerceptionFusion, LocalWorldProjector  # noqa: E402
from wowbot.vision.world3d.candidates import detect_world_candidates  # noqa: E402
from wowbot.vision.world3d.scene import build_scene_roi  # noqa: E402
from wowbot.vision.world3d.tracking import WorldCandidateTracker  # noqa: E402
from wowbot.vision.world3d.models import WorldFrameObservation  # noqa: E402
from wowbot.vision.mouseover_association import associate_mouseover  # noqa: E402
from wowbot.vision.entity_memory import EntityMemory  # noqa: E402
from wowbot.vision.visual_signature import build_visual_signature  # noqa: E402
from wowbot.vision.map_mouseover import normalize_map_mouseover  # noqa: E402
from wowbot.vision.world_point_memory import WorldPointMemory  # noqa: E402


def save_png(raw: bytes, width: int, height: int, path: Path) -> None:
    from PIL import Image
    rgba = bytearray(raw)
    for i in range(0, len(rgba), 4):
        rgba[i], rgba[i + 2] = rgba[i + 2], rgba[i]
    Image.frombytes("RGBA", (width, height), bytes(rgba)).save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Passive M7.5.6 3D Vision → Perception Fusion probe")
    parser.add_argument("--pid", type=int, default=None)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--snapshot", type=Path, default=None)
    args = parser.parse_args()

    window = find_best_wow_window(preferred_pid=args.pid)
    if window is None:
        raise RuntimeError("no visible World of Warcraft window found")
    hwnd = window.hwnd
    print(f"[wow] using PID {window.pid} hwnd={hwnd} title={window.title!r}")
    print("Passive only: no keyboard/mouse input is sent.")
    print("M7.5.6: 3D candidates → WorldObservation → PerceptionFusion")
    print("Press Ctrl+C to stop.")

    tracker = WorldCandidateTracker()
    fusion = PerceptionFusion()
    projector = LocalWorldProjector()
    samples: list[dict[str, object]] = []
    runtime_root = ROOT / "runtime" / (args.output.parent.name if args.output is not None else "client-1")
    entity_memory = EntityMemory(runtime_root / "entity_memory.sqlite3")
    world_point_memory = WorldPointMemory(runtime_root / "world_point_memory.sqlite3")
    previous_state: dict = {}
    last_visual_write: dict[str, float] = {}
    last_raw: bytes | None = None
    last_width = last_height = 0
    try:
        while True:
            raw, width, height = capture_hwnd_bgra(hwnd)
            addon_payload = decode_payload_from_bgra(raw, width, height)
            addon_state = payload_to_state(addon_payload, previous_state) if addon_payload else dict(previous_state)
            previous_state = addon_state
            mouseover = addon_state.get("mouseover")
            cursor_position = addon_state.get("cursor_position")
            map_mouseover = normalize_map_mouseover(addon_state.get("map_mouseover"))
            world_point_key = None
            observed_at = time.time()
            if width < 320 or height < 240:
                raise RuntimeError(f"selected WoW window is too small for 3D vision: {width}x{height}")
            last_raw, last_width, last_height = raw, width, height
            roi = build_scene_roi(width, height)
            if map_mouseover is not None:
                world_point_key = world_point_memory.record(
                    map_mouseover,
                    name=((addon_state.get("map_mouseover") or {}).get("unit") or {}).get("name"),
                    npc_id=((addon_state.get("map_mouseover") or {}).get("unit") or {}).get("npc_id"),
                    observed_at=observed_at,
                )
            tracked = tracker.update(detect_world_candidates(raw, width, height, roi))
            frame = WorldFrameObservation(width=width, height=height, scene=roi, candidates=tracked, observed_at=observed_at)
            fused = fusion.build_from_world3d(frame)
            local_world = projector.project(fused)
            association = associate_mouseover(
                mouseover, cursor_position, local_world.entities,
                screen_width=width, screen_height=height, max_distance_px=90.0,
            )
            visual_observation = None
            if association.matched and mouseover:
                identity_key = entity_memory.identity_key(mouseover)
                matched_candidate = next((c for c in tracked if c.track_id == association.track_id), None)
                if identity_key and matched_candidate is not None:
                    visual_observation = build_visual_signature(
                        raw, width, height, matched_candidate.rect,
                        kind=matched_candidate.kind, relation=matched_candidate.relation,
                        class_name=matched_candidate.class_name,
                    )
                    visual_observation["identity_key"] = identity_key
                    visual_observation["track_id"] = association.track_id
                    now = time.time()
                    if now - last_visual_write.get(identity_key, 0.0) >= 2.0:
                        entity_memory.record_mouseover(
                            mouseover,
                            map_id=addon_state.get("map_id"),
                            map_x=(addon_state.get("position") or {}).get("x"),
                            map_y=(addon_state.get("position") or {}).get("y"),
                            zone=addon_state.get("zone_name"),
                            observed_at=observed_at,
                        )
                        entity_memory.associate_visual(identity_key, visual_observation, observed_at)
                        last_visual_write[identity_key] = now

            world_entities = list(fused.world.visible_entities) if fused.world is not None else []
            counts: dict[str, int] = {}
            for c in tracked:
                counts[c.kind] = counts.get(c.kind, 0) + 1
            payload = {
                "width": width,
                "height": height,
                "scene_roi": {"left": roi.rect.left, "top": roi.rect.top, "right": roi.rect.right, "bottom": roi.rect.bottom, "profile": roi.profile},
                "candidate_count": len(tracked),
                "candidate_kinds": counts,
                "candidates": [
                    {"kind": c.kind, "rect": {"left": c.rect.left, "top": c.rect.top, "right": c.rect.right, "bottom": c.rect.bottom}, "confidence": c.confidence,
                     "evidence": c.evidence, "relation": c.relation, "class_name": c.class_name, "class_color": c.class_color,
                     "track_id": c.track_id, "previous_relation": c.previous_relation, "relation_changed": c.relation_changed}
                    for c in tracked
                ],
                "world_observation": {
                    "visible_entities": world_entities,
                    "obstacles": list(fused.world.obstacles) if fused.world is not None else [],
                    "observed_at": fused.world.observed_at if fused.world is not None else observed_at,
                },
                "local_world_model": local_world.to_dict(),
                "navigation_observation": {
                    "has_world": fused.world is not None,
                    "observed_at": fused.observed_at,
                },
                "addon_mouseover": mouseover,
                "cursor_position": cursor_position,
                "map_mouseover": addon_state.get("map_mouseover"),
                "world_point_memory_key": world_point_key,
                "mouseover_association": {
                    "matched": association.matched,
                    "track_id": association.track_id,
                    "distance_px": association.distance_px,
                    "confidence": association.confidence,
                    "reason": association.reason,
                },
                "visual_observation": visual_observation,
                "entity_memory": entity_memory.summary(visual_observation["identity_key"]) if visual_observation else None,
                "observed_at": observed_at,
                "source": "screen_capture",
                "notes": [],
            }
            print(json.dumps(payload, ensure_ascii=False))
            samples.append(payload)
            time.sleep(max(args.interval, 0.05))
    except KeyboardInterrupt:
        return 0
    finally:
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({"samples": samples}, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.snapshot is not None and last_raw is not None:
            args.snapshot.parent.mkdir(parents=True, exist_ok=True)
            save_png(last_raw, last_width, last_height, args.snapshot)


if __name__ == "__main__":
    raise SystemExit(main())
