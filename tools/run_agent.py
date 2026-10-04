"""User launcher. GUI starts MANUAL; --replay never accesses a live client."""
from __future__ import annotations
import argparse
import logging  # Preload stdlib before adding the existing src/logging directory.
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--goal", default="Questelj")
    parser.add_argument("--pid", type=int, help="Explicit PID prefill; never enables execution")
    parser.add_argument("--bindings-cache", type=Path, help="Explicit cache prefill; never searches other files")
    parser.add_argument("--auto-full-ai", action="store_true",
                        help="Connect to the explicit PID/cache and request FULL_AI after GUI startup")
    parser.add_argument("--with-debugger", action="store_true",
                        help="Run the read-only live debugger alongside the GUI")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "agent")
    args = parser.parse_args()
    if args.replay:
        from wowbot.agent.runtime import replay
        result = replay(args.replay, args.output, args.goal)
        print(f"OFFLINE replay: {result['frames']} frames, {len(result['commands'])} recorded commands. No client input.")
        return 0
    if args.auto_full_ai and args.pid is None:
        parser.error("--auto-full-ai requires --pid; no PID fallback is allowed")
    # Without --bindings-cache the GUI connects export-only, creates a cache
    # from the client's own binding export, then reconnects and arms.
    from wowbot.agent.gui import launch
    debugger = None
    try:
        if args.with_debugger:
            command = [sys.executable, str(ROOT / "tools" / "live_debug_monitor.py"),
                       "--output", str(args.output)]
            if args.pid is not None:
                command.extend(["--pid", str(args.pid)])
            debugger = subprocess.Popen(command, cwd=ROOT)
        launch(args.output, pid=args.pid, bindings_cache=args.bindings_cache,
               auto_full_ai=args.auto_full_ai)
    finally:
        if debugger is not None and debugger.poll() is None:
            debugger.terminate()
            try:
                debugger.wait(timeout=3)
            except subprocess.TimeoutExpired:
                debugger.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
