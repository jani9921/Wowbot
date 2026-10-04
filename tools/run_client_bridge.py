from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.client_session import clear_stale_pointer, new_session, write_session_state
from wow_window import find_best_wow_window


def load_original_bridge_module(original_project: Path):
    original_src = original_project / "src"
    if not original_src.exists():
        raise RuntimeError(f"original src directory not found: {original_src}")
    if str(original_project) not in sys.path:
        sys.path.insert(0, str(original_project))
    # Import only the functions required for the session/state bridge.
    # Vision-specific detectors are optional because the original project
    # may contain a different pixel_bridge revision.
    from src.adapters import pixel_bridge as module  # type: ignore

    required = (
        "capture_window_bgra",
        "decode_payload_from_bgra",
        "payload_to_state",
        "window_pixel_to_client_ratios",
    )
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            "Original pixel_bridge is missing required exports: " + ", ".join(missing)
        )

    return {
        name: getattr(module, name)
        for name in required
    } | {
        name: getattr(module, name, None)
        for name in (
            "detect_campfire",
            "detect_enemy_nameplate",
            "detect_friendly_nameplate",
            "detect_quest_marker",
        )
    }


def _detect_marker(bridge, raw, width, height, *, selected_enemy: bool, needs_campfire: bool):
    """Use whichever optional detector exists in the original bridge."""
    if selected_enemy and bridge.get("detect_enemy_nameplate") is not None:
        return bridge["detect_enemy_nameplate"](raw, width, height)
    if needs_campfire and bridge.get("detect_campfire") is not None:
        return bridge["detect_campfire"](raw, width, height)
    detector = bridge.get("detect_quest_marker")
    if detector is not None:
        return detector(raw, width, height)
    return None


def _detect_unit(bridge, raw, width, height):
    detector = bridge.get("detect_friendly_nameplate")
    return detector(raw, width, height) if detector is not None else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Session-aware bridge using the original AIPC decoder.")
    parser.add_argument("--original-project", required=True, type=Path)
    parser.add_argument("--runtime-dir", default="runtime/client-1")
    parser.add_argument("--client-id", default="client-1")
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()

    original = args.original_project.resolve()
    runtime = (ROOT / args.runtime_dir).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    clear_stale_pointer(runtime)
    bridge = load_original_bridge_module(original)

    intent_path = (original / args.runtime_dir / "control_intent.json").resolve()
    if not intent_path.exists():
        # Fall back to the common original runtime location if the new runtime path
        # was not used to create the intent file.
        alt = original / "runtime" / args.client_id / "control_intent.json"
        if alt.exists():
            intent_path = alt

    session = None
    previous: dict = {}
    last_character: tuple[str | None, str | None] | None = None
    last_error = None
    selected_pid: int | None = None
    last_quest_marker = None
    last_quest_marker_at = 0.0
    last_enemy_name = None
    last_enemy_marker = None
    last_enemy_marker_at = 0.0

    print(f"Session-aware pixel bridge -> {runtime}")
    print("A new session is created at startup and again when the character changes.")

    while True:
        try:
            try:
                intent = json.loads(intent_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                intent = {"mode": "PASSIVE"}
            configured_pid = None
            try:
                configured_pid = int(intent.get("pid")) if intent.get("pid") is not None else None
            except (TypeError, ValueError):
                configured_pid = None

            window = find_best_wow_window(preferred_pid=configured_pid)
            if window is None:
                raise RuntimeError(
                    f"no visible World of Warcraft window (configured pid={configured_pid})"
                )
            pid = window.pid
            if pid != selected_pid:
                selected_pid = pid
                print(
                    f"[wow] using PID {window.pid} hwnd={window.hwnd} "
                    f"process={window.process_name or '?'} title={window.title!r}"
                )
            raw, width, height = bridge["capture_window_bgra"](
                pid, ensure_foreground=intent.get("mode") == "FULL_AI"
            )
            payload = bridge["decode_payload_from_bgra"](raw, width, height)
            if payload is None:
                raise RuntimeError("AIPC pixel header not visible; keep the WoW window visible")

            # Parse without carrying old state first. This prevents stale quest pages,
            # markers and unrelated fields from crossing a login/character boundary.
            snapshot = bridge["payload_to_state"](payload, previous=None, client_id=args.client_id)
            character = snapshot.get("character_name")
            realm = snapshot.get("character_realm")
            character_key = (character, realm)
            if session is None or character_key != last_character:
                session = new_session(runtime, args.client_id, character, realm)
                previous = {}
                last_character = character_key
                last_enemy_name = None
                last_enemy_marker = None
                last_enemy_marker_at = 0.0
                last_quest_marker = None
                last_quest_marker_at = 0.0
                print(f"[session] started {session.session_id} character={character or '?'} realm={realm or '?'}")

            state = bridge["payload_to_state"](payload, previous=previous, client_id=args.client_id)
            selected_enemy = bool(state.get("current_target") and state.get("target_is_attackable") is True)
            selected_friendly = bool(state.get("current_target") and state.get("target_is_attackable") is False)
            needs_campfire = any(
                "campfire" in str(objective.get("description", "")).lower()
                and int(objective.get("current", 0)) < int(objective.get("required", 1))
                for quest in state.get("active_quests", [])
                for objective in quest.get("objectives", [])
            )
            marker = _detect_marker(
                bridge, raw, width, height,
                selected_enemy=selected_enemy,
                needs_campfire=needs_campfire,
            )
            enemy_marker_retained = False
            if selected_enemy:
                enemy_name = state.get("current_target")
                if enemy_name != last_enemy_name:
                    last_enemy_name = enemy_name
                    last_enemy_marker = None
                if marker is not None:
                    candidate = bridge["window_pixel_to_client_ratios"](pid, marker[0], marker[1], width, height)
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
                    state["vision_target_x"], state["vision_target_y"] = bridge["window_pixel_to_client_ratios"](
                        pid, marker[0], marker[1], width, height
                    )
                if not enemy_marker_retained:
                    state["vision_target_confidence"] = 0.96 if selected_enemy else (0.88 if needs_campfire else 0.84)
                if not selected_enemy and not needs_campfire:
                    last_quest_marker = (state["vision_target_x"], state["vision_target_y"])
                    last_quest_marker_at = time.time()
            elif selected_friendly and last_quest_marker is not None and time.time() - last_quest_marker_at <= 3.0:
                state["vision_target_x"], state["vision_target_y"] = last_quest_marker
                state["vision_target_confidence"] = 0.72
            else:
                state["vision_target_x"], state["vision_target_y"] = None, None
                state["vision_target_confidence"] = None
            unit = None if selected_enemy or (marker is not None and not selected_friendly) else _detect_unit(bridge, raw, width, height)
            if unit:
                state["vision_unit_x"], state["vision_unit_y"] = bridge["window_pixel_to_client_ratios"](
                    pid, unit[0], unit[1], width, height
                )
                state["vision_unit_confidence"] = 0.82
            else:
                state["vision_unit_x"], state["vision_unit_y"] = None, None
                state["vision_unit_confidence"] = None

            write_session_state(session.state_path, state, session)
            previous = state
            last_error = None
        except Exception as exc:
            message = str(exc)
            if message != last_error:
                print(f"Session bridge waiting: {message}")
                last_error = message
        time.sleep(max(args.interval, 0.1))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Session-aware bridge stopped")
