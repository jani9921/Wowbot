"""Offline replay of recorded {at, state} telemetry through one agent.

Split out of runtime.py (2026-10-05, module-size gate V4-083); unchanged and
still importable as ``wowbot.agent.runtime.replay``.  Never constructs an OS
input backend.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .engine import AutonomousAgent
from .memory import AgentMemory
from .models import Mode, canonical


def replay(path: Path, output: Path, goal="Questelj", parameters=None):
    """JSONL {at, state} observations. Never constructs an OS input backend."""
    from .executor import RecordingExecutor
    executor = RecordingExecutor()
    memory = AgentMemory(output / "replay_memory.sqlite3")
    agent = AutonomousAgent(executor, memory=memory)
    source_text = path.read_text(encoding="utf-8-sig")
    results = []
    previous_player: dict | None = None
    world_deltas: list[dict] = []
    trace: list[dict] = []
    for index, line in enumerate(source_text.splitlines(), start=1):
        if not line.strip():
            continue
        item = json.loads(line)
        at = float(item["at"])
        if agent.goal is None:
            agent.set_goal(goal, at, parameters)
            agent.set_mode(Mode.FULL_AI)
        status = agent.tick(item.get("state"), at)
        results.append(status)
        player = ((status.get("world") or {}).get("player") or {})
        changed = {key: value for key, value in player.items()
                   if previous_player is None or previous_player.get(key) != value}
        world_deltas.append({"index": index, "at": at,
                             "changed": changed,
                             "player_state_sha256": hashlib.sha256(
                                 canonical(player).encode("utf-8")).hexdigest()})
        trace.append({
            "index": index, "at": at,
            "goal": status.get("goal"), "plan": status.get("plan"),
            "decision": status.get("decision"), "pending": status.get("pending"),
            "result": status.get("result"),
            "skill_lifecycle": status.get("skill_lifecycle"),
            "supervisor": status.get("supervisor"),
            "structured_log": status.get("structured_log"),
        })
        previous_player = player
    from dataclasses import asdict
    from adapters.atomic_file import write_json_replace
    hydration = {"verified": False, "reason": "no_observations"}
    if agent.world.session_id:
        hydrated = memory.hydrate_world(agent.world.session_id)
        original_relations = set(agent.world.relations)
        hydrated_relations = set(hydrated.relations)
        original_events = {event.event_id for event in agent.world.event_records}
        hydrated_events = {event.event_id for event in hydrated.event_records}
        checks = {
            "observation_count": len(hydrated.history) == len(agent.world.history),
            "quest_state": canonical(hydrated.quest_model.snapshot()) == canonical(agent.world.quest_model.snapshot()),
            "entities": set(hydrated.entities) == set(agent.world.entities),
            "relations": hydrated_relations == original_relations,
            "events": hydrated_events == original_events,
        }
        hydration = {"verified": all(checks.values()), "checks": checks,
                     "observation_count": len(hydrated.history),
                     "missing_relations": sorted(original_relations-hydrated_relations),
                     "extra_relations": sorted(hydrated_relations-original_relations),
                     "missing_events": sorted(original_events-hydrated_events),
                     "extra_events": sorted(hydrated_events-original_events)}
    package = {
        "format": "AIPC_REPLAY_PACKAGE_V1",
        "offline": True,
        "source": {"path": str(path), "sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                   "observation_rows": len(results)},
        "config_snapshot": {"goal": goal, "parameters": dict(parameters or {}),
                            "input_backend": "RECORDING_EXECUTOR"},
        "session_metadata": {"session_id": agent.world.session_id,
                             "started_at": (results[0].get("world") or {}).get("received_at") if results else None,
                             "ended_at": (results[-1].get("world") or {}).get("received_at") if results else None},
        "frame_references": [],  # JSONL telemetry has no raster frame payload by contract.
        "world_state_deltas": world_deltas,
        "trace": trace,
        "commands": [asdict(c) for c in executor.commands],
        "failures": [entry for entry in trace
                     if (entry.get("result") or {}).get("outcome") in {"FAILURE", "CANCELLED"}],
        "hydration": hydration,
    }
    result = {"offline": True, "frames": len(results), "commands": package["commands"],
              "status": results[-1] if results else {}, "hydration": hydration,
              "replay_package": {"format": package["format"], "source_sha256": package["source"]["sha256"],
                                 "failure_count": len(package["failures"]),
                                 "trace_entries": len(trace)}}
    write_json_replace(output / "replay_result.json", result)
    write_json_replace(output / "replay_package.json", package)
    return result
