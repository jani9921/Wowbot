from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Allow running directly from a source checkout.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.navigation.world_context import MapIdentityResolver  # noqa: E402


def load_state(path: Path) -> dict[str, object] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        print(f"[probe] invalid JSON in {path}: {exc}")
        return None
    if not isinstance(data, dict):
        print(f"[probe] state root must be an object: {path}")
        return None
    return data


def show(data: dict[str, object]) -> None:
    resolver = MapIdentityResolver()
    position = data.get("position")
    context = resolver.resolve(
        map_id=data.get("map_id"),
        continent=data.get("continent"),
        zone=data.get("zone_name"),
        subzone=data.get("subzone_name"),
        instance_type=data.get("instance_type"),
        coordinate_space="world",
    )

    print("=" * 72)
    print("WoW Navigation — M7.1 Client Probe")
    print("=" * 72)
    print(f"timestamp       : {data.get('timestamp', time.time())}")
    print(f"character       : {data.get('character_name') or '?'}")
    print(f"client map_id   : {data.get('map_id')}")
    print(f"zone            : {data.get('zone_name') or '?'}")
    print(f"subzone         : {data.get('subzone_name') or '?'}")
    print(f"canonical id    : {context.context_id}")
    print(f"semantic key    : {context.semantic_key}")
    print(f"context conf.   : {context.confidence:.2f}")
    print(f"coordinate space : {context.coordinate_space}")

    if isinstance(position, dict):
        print("map position    :", f"x={position.get('x')} y={position.get('y')} z={position.get('z', 0)}")
        print("position note   : addon position is treated as MAP-SPACE, not world XYZ")
    else:
        print("map position    : <missing>")

    world_position = data.get("world_position")
    if isinstance(world_position, dict):
        print(
            "world position  :",
            f"x={world_position.get('x')} y={world_position.get('y')} z={world_position.get('z', 0)}",
        )
    else:
        print("world position  : <not supplied by client>")

    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect live addon state for M7.1 WorldContext mapping.")
    parser.add_argument("--state", type=Path, default=None, help="Path to a specific live state.json file")
    parser.add_argument("--runtime-root", type=Path, default=None, help="Session runtime root; follows current_session.json automatically")
    parser.add_argument("--watch", action="store_true", help="Keep watching until Ctrl+C")
    parser.add_argument("--resolve-map", action="store_true", help="Print the canonical WorldContext mapping repeatedly even when map facts are incomplete")
    parser.add_argument("--interval", type=float, default=1.0, help="Watch interval in seconds")
    args = parser.parse_args()

    last_signature = None
    try:
        while True:
            state_path = args.state
            if state_path is None and args.runtime_root is not None:
                pointer = args.runtime_root / "current_session.json"
                state_path = None
                try:
                    pointer_data = json.loads(pointer.read_text(encoding="utf-8"))
                    rel = pointer_data.get("state_path")
                    if rel:
                        state_path = Path(rel)
                except (FileNotFoundError, json.JSONDecodeError, OSError):
                    pass
                if state_path is None:
                    matches = sorted(args.runtime_root.glob("session-*/state.json"), key=lambda q: q.stat().st_mtime, reverse=True) if args.runtime_root.exists() else []
                    state_path = matches[0] if matches else None
            if state_path is None:
                if not args.watch:
                    print(f"[probe] waiting for session state under {args.runtime_root}")
                    return 2
                time.sleep(max(args.interval, 0.1))
                continue
            data = load_state(state_path)
            if data is None:
                if not args.watch:
                    print(f"[probe] waiting for state file: {state_path}")
                    return 2
            else:
                signature = (data.get("timestamp"), data.get("map_id"), data.get("zone_name"), data.get("subzone_name"), repr(data.get("position")))
                if signature != last_signature:
                    show(data)
                    last_signature = signature
            if not args.watch:
                return 0
            time.sleep(max(args.interval, 0.1))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
