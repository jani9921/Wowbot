from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# Running `py tools\...` puts only the tools directory on sys.path.
# Add the project root so both `src.*` and `tools.*` imports resolve.
for entry in (ROOT, SRC):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from wowbot.vision.adapters.minimap import detect_minimap  # noqa: E402
try:
    from src.adapters.pixel_bridge import capture_window_bgra  # noqa: E402
except ModuleNotFoundError:
    from adapters.pixel_bridge import capture_window_bgra  # noqa: E402


def marker_payload(obs) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for marker in obs.markers:
        dx, dy = obs.marker_relative(marker)
        nx, ny = obs.marker_normalized(marker)
        rows.append(
            {
                "type": marker.marker_type,
                "x": marker.position.x,
                "y": marker.position.y,
                "confidence": round(marker.confidence, 4),
                "marker_color": marker.marker_color,
                "relation": marker.relation,
                "symbol": marker.symbol,
                "bearing_degrees": getattr(marker, "bearing_degrees", None),
                "relative_x_px": round(dx, 3),
                "relative_y_px": round(dy, 3),
                "normalized_x": round(nx, 5),
                "normalized_y": round(ny, 5),
                "distance_px": round(obs.marker_distance_px(marker), 3),
            }
        )
    return rows


def signature(obs) -> tuple:
    markers = []
    for marker in sorted(obs.markers, key=lambda m: (m.marker_type, m.position.x, m.position.y)):
        markers.append(
            (
                marker.marker_type,
                marker.position.x,
                marker.position.y,
                marker.marker_color,
                marker.relation,
                marker.symbol,
            )
        )
    return (
        obs.width,
        obs.height,
        obs.player_marker.x,
        obs.player_marker.y,
        tuple(markers),
    )


def choose_pid(pid: int | None) -> int:
    if pid is not None:
        return pid
    from tools.wow_window import find_best_wow_window, find_visible_wow_windows
    window = find_best_wow_window()
    if window is None:
        candidates = find_visible_wow_windows()
        if candidates:
            details = ", ".join(f"{w.pid}:{w.title}" for w in candidates)
            raise RuntimeError(f"no suitable WoW window; visible candidates: {details}")
        raise RuntimeError("no visible World of Warcraft window found")
    print(f"[wow] using PID {window.pid} hwnd={window.hwnd} title={window.title!r}")
    return window.pid


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live passive Minimap perception probe; captures the visible WoW window and emits marker observations."
    )
    parser.add_argument("--pid", type=int, default=None, help="WoW process PID; omitted = auto-detect visible WoW window")
    parser.add_argument("--interval", type=float, default=0.25, help="Sampling interval in seconds")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSONL output file")
    parser.add_argument("--all", action="store_true", help="Print every sample instead of only changes")
    args = parser.parse_args()

    pid = choose_pid(args.pid)
    last_sig = None
    output_handle = None
    saved_samples: list[dict[str, object]] = []
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("WoW Navigation — M7.4.4 Live Minimap Probe")
    print("=" * 72)
    print("Passive only: no keyboard/mouse input is sent.")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            raw, width, height = capture_window_bgra(pid)
            obs = detect_minimap(raw, width, height, observed_at=time.time())
            payload = {
                "width": obs.width,
                "height": obs.height,
                "player_marker": {"x": obs.player_marker.x, "y": obs.player_marker.y},
                "center_radius_px": round(obs.center_radius_px, 3),
                "observed_at": obs.observed_at,
                "markers": marker_payload(obs),
            }
            sig = signature(obs)
            if args.all or sig != last_sig:
                print(json.dumps(payload, ensure_ascii=False))
                saved_samples.append(payload)
                last_sig = sig
            time.sleep(max(args.interval, 0.05))
    except KeyboardInterrupt:
        return 0
    finally:
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({"samples": saved_samples}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
