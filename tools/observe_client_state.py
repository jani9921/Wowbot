from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.adapters.file_bridge import JsonFileBridge
from src.adapters.atomic_file import write_json_replace
from src.core.client_observation import PassiveClientObserver
from src.core.observation_replay import ObservationRecorder, to_jsonable
from src.core.perception_fusion import PerceptionFusion, PerceptionFusionConfig
from src.core.quest_database import QuestDatabase
from src.core.quest_planner import QuestPlanner, QuestPlannerConfig
from src.core.quest_routes import QuestRouteCatalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Passively observe AIPC client state; never sends commands.")
    parser.add_argument("--bridge-dir", default="runtime/client-1")
    parser.add_argument("--client-id", default="client-1")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--samples", type=int, default=0, help="0 keeps observing until Ctrl+C")
    args = parser.parse_args()

    bridge_dir = (REPO_ROOT / args.bridge_dir).resolve()
    bridge = JsonFileBridge(args.client_id, bridge_dir)
    database = QuestDatabase.from_project_defaults()
    planner = QuestPlanner(database, QuestPlannerConfig.from_file(REPO_ROOT / "config" / "quest_planner.json"))
    observer = PassiveClientObserver(
        planner,
        PerceptionFusion(PerceptionFusionConfig.from_file(REPO_ROOT / "config" / "world_model.json")),
    )
    routes = QuestRouteCatalog.from_file(REPO_ROOT / "data" / "exiles_reach_routes.json")
    recorder = ObservationRecorder(bridge_dir / "observations.jsonl")
    report_path = bridge_dir / "observation_latest.json"
    count = 0
    print("PASSIVE OBSERVER: no input or client command execution is enabled")
    while args.samples <= 0 or count < args.samples:
        state = routes.enrich_state(bridge.read_state())
        snapshot = observer.observe(state)
        recorder.record(snapshot)
        write_json_replace(
            report_path,
            to_jsonable(snapshot.diagnostics()),
            ensure_ascii=False,
        )
        print(
            f"OBSERVE trace={snapshot.trace_id} source={state.telemetry_source} "
            f"world_confidence={snapshot.world_model.system_confidence:.2f} "
            f"findings={len(snapshot.findings)}"
        )
        count += 1
        if args.samples <= 0 or count < args.samples:
            time.sleep(max(0.05, args.interval))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Passive observation stopped")
