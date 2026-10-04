from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.adapters.pixel_bridge import (
    capture_window_bgra, decode_payload_from_bgra, detect_campfire, detect_enemy_nameplate, detect_friendly_nameplate,
    detect_quest_marker, payload_to_state,
    window_pixel_to_client_ratios, write_state_atomic,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Decode the AIPC retail addon pixel strip into state.json.")
    parser.add_argument("--bridge-dir", default="runtime/client-1")
    parser.add_argument("--client-id", default="client-1")
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    directory = (REPO_ROOT / args.bridge_dir).resolve()
    intent_path, state_path = directory / "control_intent.json", directory / "state.json"
    print(f"Pixel bridge -> {state_path}")
    last_error = None
    last_quest_marker = None
    last_quest_marker_at = 0.0
    last_enemy_name = None
    last_enemy_marker = None
    last_enemy_marker_at = 0.0
    while True:
        try:
            intent = json.loads(intent_path.read_text(encoding="utf-8"))
            pid = int(intent["pid"])
            raw, width, height = capture_window_bgra(pid, ensure_foreground=intent.get("mode") == "FULL_AI")
            payload = decode_payload_from_bgra(raw, width, height)
            if payload is None:
                raise RuntimeError("AIPC pixel header not visible; keep the WoW window visible")
            previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
            state = payload_to_state(payload, previous, args.client_id)
            selected_enemy = bool(state.get("current_target") and state.get("target_is_attackable") is True)
            selected_friendly = bool(state.get("current_target") and state.get("target_is_attackable") is False)
            needs_campfire = any(
                "campfire" in str(objective.get("description", "")).lower()
                and int(objective.get("current", 0)) < int(objective.get("required", 1))
                for quest in state.get("active_quests", [])
                for objective in quest.get("objectives", [])
            )
            marker = detect_enemy_nameplate(raw, width, height) if selected_enemy else (
                detect_campfire(raw, width, height) if needs_campfire else (
                    detect_quest_marker(raw, width, height)
                )
            )
            enemy_marker_retained = False
            if selected_enemy:
                enemy_name = state.get("current_target")
                if enemy_name != last_enemy_name:
                    last_enemy_name = enemy_name
                    last_enemy_marker = None
                if marker is not None:
                    candidate = window_pixel_to_client_ratios(pid, marker[0], marker[1], width, height)
                    if last_enemy_marker is None:
                        last_enemy_marker = candidate
                    else:
                        dx = candidate[0] - last_enemy_marker[0]
                        dy = candidate[1] - last_enemy_marker[1]
                        if dx * dx + dy * dy <= 0.16 * 0.16:
                            last_enemy_marker = (
                                last_enemy_marker[0] * 0.65 + candidate[0] * 0.35,
                                last_enemy_marker[1] * 0.65 + candidate[1] * 0.35,
                            )
                        else:
                            # A large one-frame jump is another nearby gold
                            # nameplate, not the selected target.
                            marker = None
                    if marker is not None:
                        last_enemy_marker_at = time.time()
                if marker is None and last_enemy_marker is not None and time.time() - last_enemy_marker_at <= 0.7:
                    state["vision_target_x"], state["vision_target_y"] = last_enemy_marker
                    state["vision_target_confidence"] = 0.74
                    enemy_marker_retained = True
            if marker or enemy_marker_retained:
                if selected_enemy and last_enemy_marker is not None:
                    state["vision_target_x"], state["vision_target_y"] = last_enemy_marker
                else:
                    state["vision_target_x"], state["vision_target_y"] = window_pixel_to_client_ratios(pid, marker[0], marker[1], width, height)
                if not enemy_marker_retained:
                    state["vision_target_confidence"] = 0.96 if selected_enemy else (0.88 if needs_campfire else 0.84)
                if not selected_enemy and not needs_campfire:
                    last_quest_marker = (state["vision_target_x"], state["vision_target_y"])
                    last_quest_marker_at = time.time()
            elif selected_friendly and last_quest_marker is not None and time.time() - last_quest_marker_at <= 3.0:
                # Selecting the NPC removes its overhead quest marker. Retain
                # the immediately preceding bearing briefly so an out-of-range
                # interaction can approach in short, verified pulses.
                state["vision_target_x"], state["vision_target_y"] = last_quest_marker
                state["vision_target_confidence"] = 0.72
            else:
                state["vision_target_x"], state["vision_target_y"] = None, None
                state["vision_target_confidence"] = None
            unit = None if selected_enemy or (marker is not None and not selected_friendly) else detect_friendly_nameplate(raw, width, height)
            if unit:
                state["vision_unit_x"], state["vision_unit_y"] = window_pixel_to_client_ratios(pid, unit[0], unit[1], width, height)
                state["vision_unit_confidence"] = 0.82
            else:
                state["vision_unit_x"], state["vision_unit_y"] = None, None
                state["vision_unit_confidence"] = None
            write_state_atomic(state_path, state)
            last_error = None
        except Exception as exc:
            message = str(exc)
            if message != last_error:
                print(f"Pixel bridge waiting: {message}")
                last_error = message
        time.sleep(args.interval)


if __name__ == "__main__":
    try: raise SystemExit(main())
    except KeyboardInterrupt: print("Pixel bridge stopped")
