"""Offline REV4 boundary probes; recording executor, no client/capture input."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys


def run(project: Path) -> dict:
    sys.path.insert(0, str(project / "src"))
    from wowbot.agent.engine import AutonomousAgent
    from wowbot.agent import tdb_locations
    from wowbot.agent.objective_locator import ObjectiveLocator
    from wowbot.navigation.danger import DangerMap
    from wowbot.packetio.context import addon_context_status

    class NoInput:
        def __init__(self):
            self.calls = []

        def execute(self, commands):
            self.calls.append(commands)
            raise AssertionError("This audit must never dispatch client input")

        execute_movement = execute

    first_input, second_input = NoInput(), NoInput()
    first = AutonomousAgent(first_input, navmesh=object())
    first_owned_before = tdb_locations.route_cost_oracle.__self__ is first.navigation
    second = AutonomousAgent(second_input, navmesh=object())
    first_owned_after = tdb_locations.route_cost_oracle.__self__ is first.navigation
    second_owned_after = tdb_locations.route_cost_oracle.__self__ is second.navigation

    objective = SimpleNamespace(
        target_entity={}, target_location={"map_id": 2023, "x": .5, "y": .5,
                                           "source": "QUEST_API"}, confidence=1.)
    record = SimpleNamespace(quest_id=1)
    static_region = {"map_id": 2023, "x": .1, "y": .1, "source": "TDB_SPAWN"}
    with patch.object(tdb_locations, "objective_region", return_value=static_region):
        location = ObjectiveLocator().locate(objective, record, {"map_id": 2023})

    danger = DangerMap()
    danger.observe_hostiles({"nearby_attackable_entities": [{
        "guid": "audit-hostile", "attackable": True,
        "world_position": {"x": 10., "y": 10.},
        "source": "PACKET_ENTITY", "confidence": 1.,
    }]}, 1.)
    danger_sources = [entry["source"] for entry in danger.snapshot(1.)]

    result = {
        "scope": "synthetic offline probes, same Python process, no live input",
        "global_oracle": {
            "first_owned_before_second_constructor": first_owned_before,
            "first_owned_after_second_constructor": first_owned_after,
            "second_owned_after_second_constructor": second_owned_after,
        },
        "objective_location": {
            "both_sources_available": True,
            "selected_source": location.coordinates["source"],
            "selected_coordinates": location.coordinates,
        },
        "missing_packet_bootstrap_context": addon_context_status({}),
        "danger_provenance": {
            "input_source": "PACKET_ENTITY", "recorded_sources": danger_sources,
        },
        "input_command_groups": len(first_input.calls) + len(second_input.calls),
    }
    assert first_owned_before and not first_owned_after and second_owned_after
    assert result["objective_location"]["selected_source"] == "TDB_SPAWN"
    assert result["missing_packet_bootstrap_context"] == "waiting_for_addon_context"
    assert danger_sources == ["ADDON_TELEMETRY"]
    assert result["input_command_groups"] == 0
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.project.resolve())
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
