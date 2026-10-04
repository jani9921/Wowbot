from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.core.client_observation import PassiveClientObserver
from src.core.client_test_report import ClientTestReport
from src.core.observation_replay import replay_records, to_jsonable
from src.core.perception_fusion import PerceptionFusion, PerceptionFusionConfig
from src.core.quest_database import QuestDatabase
from src.core.quest_planner import QuestPlanner, QuestPlannerConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay normalized AIPC observations without client input.")
    parser.add_argument("recording")
    parser.add_argument("--client-id", default="client-1")
    parser.add_argument("--output-dir", default="runtime/replay")
    args = parser.parse_args()

    output = (REPO_ROOT / args.output_dir).resolve()
    planner = QuestPlanner(
        QuestDatabase.from_project_defaults(),
        QuestPlannerConfig.from_file(REPO_ROOT / "config" / "quest_planner.json"),
    )
    observer = PassiveClientObserver(
        planner,
        PerceptionFusion(PerceptionFusionConfig.from_file(REPO_ROOT / "config" / "world_model.json")),
    )
    report = ClientTestReport()
    output.mkdir(parents=True, exist_ok=True)
    first_recorded_at = None
    replay_started = time.monotonic()
    count = 0
    findings = 0
    sources = set()
    for trace_id, recorded_at, state in replay_records(args.recording, args.client_id):
        first_recorded_at = recorded_at if first_recorded_at is None else first_recorded_at
        replay_now = replay_started + max(0.0, recorded_at - first_recorded_at)
        snapshot = observer.observe(state, now=replay_now, wall_now=recorded_at)
        (output / f"{count:05d}-{trace_id or 'frame'}.json").write_text(
            json.dumps(to_jsonable(snapshot.diagnostics(replay_now)), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        count += 1
        findings += len(snapshot.findings)
        if state.telemetry_source:
            sources.add(state.telemetry_source)
    report.add("CLIENT DATA SOURCES OBSERVED", ", ".join(sorted(sources)) or "no declared source")
    report.add("WORLD MODEL VALIDATION RESULTS", f"{count} frames replayed; {findings} validation findings")
    report.add("RECOMMENDED NEXT DEVELOPMENT PRIORITIES", "Resolve recorded validation findings before controlled execution")
    report.write(output / "client_integration_report.md")
    print(f"Replayed {count} observations; report: {output / 'client_integration_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
