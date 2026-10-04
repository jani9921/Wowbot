"""Replay a recorded telemetry-*.jsonl through an offline AutonomousAgent.

No input reaches the client: a RecordingExecutor collects the commands.
Prints every change of the agent's decision so a live session can be
re-run against new code.  The agent cannot move the recorded character, so
outcomes that need the world to react are not reproduced -- the point is
what the planner *chooses* from the observed states.

Usage: python tools/replay_telemetry_decisions.py <telemetry.jsonl> [--goal TEXT] [--grep TEXT]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from wowbot.agent.engine import AutonomousAgent  # noqa: E402
from wowbot.agent.executor import RecordingExecutor  # noqa: E402
from wowbot.agent.models import Mode  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--goal", default="Questelj az Exile's Reach szigeten")
    parser.add_argument("--grep", default="", help="only print decisions whose text contains this")
    args = parser.parse_args()
    executor = RecordingExecutor()
    agent = AutonomousAgent(executor)
    first = True
    previous = None
    with open(args.path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            state, at = row.get("state"), row.get("at")
            if not isinstance(state, dict) or at is None:
                continue
            if first:
                agent.set_goal(args.goal, float(at))
                agent.set_mode(Mode.FULL_AI)
                first = False
            before = len(executor.commands)
            result = agent.tick(state, float(at))
            decision = result.get("decision") or {}
            mouse = state.get("mouseover") or {}
            key = (result.get("mode"), decision.get("skill"), str(decision.get("reason") or "")[:70])
            if key != previous:
                text = f"{at:10.2f} {key} mouse={str(mouse.get('tooltip') or '')[:50]!r}"
                commands = executor.commands[before:]
                if commands:
                    text += " cmds=" + ",".join(f"{c.kind}:{c.binding or ''}" for c in commands[:3])
                if args.grep in text:
                    print(text)
                previous = key
            if result.get("mode") != "FULL_AI":
                agent.set_mode(Mode.FULL_AI)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
