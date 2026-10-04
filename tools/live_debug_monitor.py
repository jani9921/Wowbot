"""Read-only live monitor for AIPC agent_status.json files.

The monitor never opens the game process and never sends input. It follows the
atomic status snapshots written by the selected agent runtime and records a
compact, replayable change stream for diagnosis.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wowbot.agent.acceptance import AcceptanceAccumulator
from wowbot.agent.obstacle_perception import obstacle_bearing


class RotatingJsonlWriter:
    """Append JSONL without allowing an unattended debugger to fill a disk."""

    def __init__(self, path: Path, *, max_bytes: int, backups: int = 4):
        if max_bytes <= 0 or backups < 1:
            raise ValueError("max_bytes must be positive and backups must be at least one")
        self.path = path
        self.max_bytes = int(max_bytes)
        self.backups = int(backups)

    def _backup(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.stem}.{index}{self.path.suffix}")

    def _rotate(self) -> None:
        oldest = self._backup(self.backups)
        if oldest.exists():
            oldest.unlink()
        for index in range(self.backups - 1, 0, -1):
            source = self._backup(index)
            if source.exists():
                source.replace(self._backup(index + 1))
        if self.path.exists():
            self.path.replace(self._backup(1))

    def write(self, value: dict) -> None:
        encoded = (json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                              default=str) + "\n").encode("utf-8")
        current_size = self.path.stat().st_size if self.path.exists() else 0
        if current_size and current_size + len(encoded) > self.max_bytes:
            self._rotate()
        with self.path.open("ab") as stream:
            stream.write(encoded)


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _short(value: Any, limit: int = 90) -> str:
    text = "-" if value in (None, "") else str(value).replace("\r", " ").replace("\n", " ")
    return text if len(text) <= limit else text[:limit-1] + "…"


def discover_status(output: Path, pid: int | None = None) -> Path | None:
    candidates = list(output.glob("pid-*/agent_status.json"))
    if pid is not None:
        candidates = [path for path in candidates if path.parent.name == f"pid-{pid}"]
    candidates = [path for path in candidates if path.is_file()]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def summarize(status: dict) -> dict:
    world = _dict(status.get("world"))
    player = _dict(world.get("player"))
    target = _dict(player.get("target") or world.get("target"))
    decision, result = _dict(status.get("decision")), _dict(status.get("result"))
    loop = _dict(status.get("autonomous_loop"))
    commitment = _dict(loop.get("commitment"))
    movement = _dict(status.get("movement_controller"))
    vision = _dict(status.get("vision_diagnostics"))
    v3 = _dict(vision.get("world3d_v3_v4"))
    v2 = _dict(v3.get("detector")) or _dict(vision.get("world3d_v2"))
    tracker = _dict(v3.get("tracker"))
    ocr = _dict(v3.get("ocr"))
    hard_examples = _dict(vision.get("hard_examples"))
    world_lane, mini_lane = _dict(vision.get("world")), _dict(vision.get("minimap"))
    tracks = _list(vision.get("tracks"))
    stable_world = [track for track in tracks
                    if track.get("source") == "WORLD3D" and track.get("state") in {"STABLE", "ACTIVE", "REACQUIRE_CANDIDATE"}]
    quests = player.get("active_quests") if isinstance(player.get("active_quests"), list) else world.get("quests")
    binding = _dict(status.get("binding_preflight"))
    map_inspection = _dict(status.get("map_inspection"))
    return {
        "pid": status.get("pid"), "mode": status.get("mode"), "sensor": status.get("sensor"),
        "fresh": world.get("fresh"), "sensor_age": world.get("sensor_age"),
        "session_id": world.get("session_id"), "map_id": player.get("map_id", world.get("map_id")),
        "position": player.get("position", world.get("position")),
        "decision": {"skill": decision.get("skill"), "reason": decision.get("reason")},
        "result": {key: result.get(key) for key in ("outcome", "skill", "reason", "failure_type", "action_id")},
        "pending": _dict(status.get("pending")).get("skill"),
        "runtime_error": status.get("runtime_error"),
        "phase": loop.get("phase"), "replan_trigger": loop.get("last_replan_trigger"),
        "replan_revision": loop.get("replan_revision"),
        "commitment": {key: commitment.get(key) for key in
                       ("commitment_id", "kind", "reference", "target_guid", "initial_skill", "status", "failures")},
        "movement": {key: movement.get(key) for key in
                     ("phase", "target", "progress_state", "stuck_belief", "no_progress_count", "reason")},
        "target": {key: target.get(key) for key in ("guid", "npc_id", "name", "attackable", "dead", "is_dead")},
        # PREPARED 2026-09-14, UNTESTED LIVE, alongside combat_hint
        # (AIPlayerControllerExport.lua/telemetry_packets.py/world.py). Both
        # values stay None until a live run with addon 0.9.18+ actually lands
        # a spell cast; this is the field to watch to confirm the fast-lane
        # confirmation reaches world.state at all, and combat_last_cast_at
        # changing on each new landed cast (not just the first) confirms it
        # keeps updating rather than sticking on a stale value.
        "combat_hint": {"spell_id": player.get("combat_last_spell_id"),
                        "cast_at": player.get("combat_last_cast_at")},
        # PREPARED 2026-09-14, UNTESTED LIVE, alongside obstacle_perception.py.
        # `count` is how many currently tracked visual_candidates got tagged
        # `detector_kind: "obstacle_candidate"` this tick (see that module for
        # the static/tall/close/stable heuristic); `bearing` is their average
        # screen-x, the same value RECOVER uses to pick a strafe direction.
        # Watch this the first time RECOVER fires live: does count go
        # nonzero only when something is actually visibly blocking the
        # character, and does bearing look like the right side of the obstacle?
        "obstacle": {"count": sum(1 for item in _list(player.get("visual_candidates"))
                                  if item.get("detector_kind") == "obstacle_candidate"),
                     "bearing": obstacle_bearing(player)},
        # PREPARED 2026-09-14, UNTESTED LIVE. AutoLabeledExampleCollector
        # (vision_dataset.py) -- Stage 1 of finishing the "V4 active-learning
        # foundation" (docs/VISION_V3_V4.md) that was scaffolded but never
        # completed. `saved` climbing during a real session is what proves
        # mouseover-confirmed identities are actually getting matched to a
        # tracked visual candidate and saved; if it stays at 0 all session,
        # either mouseover isn't landing near any tracked subject candidate,
        # or nothing is being moused over at all.
        "vision_dataset": status.get("vision_dataset"),
        "quest_count": len(quests) if isinstance(quests, list) else None,
        "binding_ready": binding.get("ready"), "missing_bindings": binding.get("missing"),
        "map_inspection": {key: map_inspection.get(key) for key in
                           ("zoom_supported", "zoom_count", "zoom_limit", "zoom_requested", "map_probes",
                            "search_stage", "map_search_exhausted")},
        "vision": {"world_status": world_lane.get("status"), "world_ms": world_lane.get("duration_ms"),
                   "world_candidates": world_lane.get("candidates"), "minimap_status": mini_lane.get("status"),
                   "minimap_ms": mini_lane.get("duration_ms"), "minimap_candidates": mini_lane.get("candidates"),
                   "stable_world_tracks": len(stable_world), "camera_motion": v2.get("camera_motion_px"),
                   "generic_candidates": v2.get("generic_candidates"), "output_candidates": v2.get("output_candidates"),
                   "pipeline_version": v3.get("version"), "perception_mode": v3.get("mode"),
                   "detector_refreshed": v2.get("refreshed"), "detector_refresh_ms": v2.get("last_refresh_ms"),
                   "tracker_mode": tracker.get("mode"), "tracker_tracks": tracker.get("tracks"),
                   "ocr_backend": ocr.get("backend"), "ocr_status": ocr.get("status"),
                   "ocr_texts": ocr.get("texts"), "hard_examples": hard_examples.get("saved"),
                   # Perception context resets restart all visual identities.
                   "context_resets": world_lane.get("context_resets"),
                   "context_reset_fields": world_lane.get("context_reset_fields"),
                   "ui_flag_raw_flips": world_lane.get("ui_flag_raw_flips"),
                   "context_reset_last": (_list(world_lane.get("context_reset_reasons")) or [None])[-1],
                   # Compact public WORLD3D track trace: id, state, upstream id,
                   # hits, missing frames.  Explains SEEK/approach track loss.
                   "world_tracks": [
                       [track.get("track_id"), track.get("state"),
                        track.get("upstream_track_id"), track.get("hits"),
                        track.get("missing_frames")]
                       for track in tracks if track.get("source") == "WORLD3D"][:12]},
        "timings_ms": status.get("timings_ms"),
        "loop_rates": status.get("loop_rates"),
        "runtime_scheduler": status.get("runtime_scheduler"),
        "camera_controller": status.get("camera_controller"),
        "visual_approach": status.get("visual_approach"),
        "vision_seek": {key: _dict(status.get("vision_seek")).get(key) for key in
                        ("phase", "target_track_id", "candidate_score", "last_x",
                         "last_bbox_height", "scan_index")},
        "combat_controller": status.get("combat_controller"),
        "skill_lifecycle": status.get("skill_lifecycle"),
        "memory_metrics": status.get("memory_metrics"),
        "maintenance": status.get("maintenance"),
        "reasoner": status.get("reasoner"),
        "input_safety": status.get("input_safety"),
        # BufferedPixelSensor's own capture+decode cost (its background
        # thread's poll_ms), distinct from timings_ms.sensor which only
        # measures the mailbox read in step() -- built in sensor.py but
        # never surfaced here before, so the real transport bottleneck
        # (GDI capture vs. pixel-strip decode vs. GIL contention) was
        # invisible. Investigated 2026-09-12 after "why is everything so
        # low-Hz": decode_payload_from_bgra() benchmarked at ~3.3ms even at
        # the max 1000-byte payload, so it is NOT the bottleneck -- this
        # field is what will show whether capture or scheduling is.
        "sensor_diagnostics": status.get("sensor_diagnostics"),
        # Main-thread mailbox consumption, distinct from sensor_diagnostics
        # (the background capture thread). Added alongside it 2026-09-12
        # after finding a case where the background thread's polls/updates
        # stayed healthy for 5.6s while receive_gap climbed the whole time --
        # this pinpoints whether AgentRuntime.step() is actually getting
        # payloads out of BufferedPixelSensor's mailbox during a stall.
        "main_thread_poll": status.get("main_thread_poll"),
    }


def signature(summary: dict) -> str:
    return json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def telemetry_row(status: dict, at: float) -> dict | None:
    """{"at", "state"} row for wowbot.agent.runtime.replay(), or None to skip.

    world.player is the exact dict AutonomousAgent.tick() ingests as `payload`
    live, so no AIPC5 decoding is needed to make a session replayable -- see
    the note above this function's call site in main().
    """
    player = _dict(_dict(status.get("world")).get("player"))
    return {"at": at, "state": player} if player else None


def format_change(current: dict, previous: dict | None) -> list[str]:
    lines: list[str] = []
    previous = previous or {}
    core_keys = ("mode", "sensor", "fresh", "session_id", "map_id", "phase", "replan_trigger",
                 "decision", "result", "pending", "commitment", "movement", "target", "quest_count",
                 "binding_ready", "missing_bindings", "runtime_error", "map_inspection", "combat_hint",
                 "obstacle", "vision_dataset")
    core_keys = (*core_keys, "loop_rates", "runtime_scheduler", "camera_controller",
                 "visual_approach", "combat_controller", "skill_lifecycle",
                 "memory_metrics", "maintenance", "reasoner", "sensor_diagnostics", "main_thread_poll")
    for key in core_keys:
        if current.get(key) != previous.get(key):
            lines.append(f"{key}={_short(current.get(key))}")
    vision, old_vision = _dict(current.get("vision")), _dict(previous.get("vision"))
    if vision != old_vision:
        lines.append("vision=" + _short(
            f"world:{vision.get('world_status')} {vision.get('world_ms')}ms/{vision.get('world_candidates')} "
            f"mini:{vision.get('minimap_status')} {vision.get('minimap_ms')}ms/{vision.get('minimap_candidates')} "
            f"stable3d:{vision.get('stable_world_tracks')} generic:{vision.get('generic_candidates')} "
            f"tracker:{vision.get('tracker_tracks')} ocr:{vision.get('ocr_status')}/{vision.get('ocr_texts')} "
            f"camera:{vision.get('camera_motion')}"))
    return lines


def read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "agent")
    parser.add_argument("--pid", type=int, help="Follow only this explicitly selected agent PID directory")
    parser.add_argument("--status", type=Path, help="Follow one explicit agent_status.json")
    parser.add_argument("--poll", type=float, default=.15)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--duration", type=float,
                        help="Read-only acceptance duration in seconds (3600/14400/28800)")
    parser.add_argument("--telemetry-max-mb", type=float, default=64.,
                        help="Maximum size of each replay JSONL segment (default: 64 MiB)")
    parser.add_argument("--event-max-mb", type=float, default=16.,
                        help="Maximum size of each event JSONL segment (default: 16 MiB)")
    parser.add_argument("--log-backups", type=int, default=4,
                        help="Number of rotated segments retained per log (default: 4)")
    args = parser.parse_args()

    debug_dir = ROOT / "output" / "live-debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    session_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    event_path = debug_dir / f"live-debug-{session_stamp}.jsonl"
    # Full-state replay trace, added 2026-09-14. agent_status.json already
    # carries world.player -- the exact same dict shape AutonomousAgent.tick()
    # ingests as `payload` -- so recording it here needs no addon-payload
    # decoding at all, unlike the (verified, live-tested) dead end of trying
    # to reassemble AIPC5 packets from saved screenshots: those are only
    # captured every ~0.5s (see LiveCaptureRecorder / this same write-gate in
    # runtime.py's step()), far too sparse to ever collect every page of a
    # multi-page STATE_Z snapshot, so PacketAssembler.feed() never completes
    # from real live-capture directories (confirmed 0/180 frames across
    # several real segments in tools/screenshot_session_replay.py). This
    # sidesteps that entirely: whatever a session recorded here can be
    # replayed afterward with wowbot.agent.runtime.replay(), fully offline,
    # without WoW or the addon -- but only for sessions run AFTER this change,
    # since no history survives from before it.
    telemetry_path = debug_dir / f"telemetry-{session_stamp}.jsonl"
    telemetry_writer = RotatingJsonlWriter(
        telemetry_path, max_bytes=int(args.telemetry_max_mb * 1024 * 1024),
        backups=args.log_backups)
    event_writer = RotatingJsonlWriter(
        event_path, max_bytes=int(args.event_max_mb * 1024 * 1024),
        backups=args.log_backups)
    telemetry_started = time.monotonic()
    selected: Path | None = args.status.resolve() if args.status else None
    previous_summary: dict | None = None
    previous_mtime = -1
    last_wait_notice = 0.0
    monitor_started = time.monotonic()
    acceptance = AcceptanceAccumulator(monitor_started)
    print("AIPC LIVE DEBUGGER (READ-ONLY) — Ctrl+C stops the monitor", flush=True)
    print(f"event_log={event_path}", flush=True)
    print(f"replay_telemetry={telemetry_path}", flush=True)
    try:
        while True:
            if args.status is None:
                newest = discover_status(args.output, args.pid)
                if newest is not None and (selected is None or not selected.exists()
                        or newest.stat().st_mtime_ns > selected.stat().st_mtime_ns):
                    if newest != selected:
                        print(f"FOLLOW {newest}", flush=True)
                        previous_summary = None
                    selected, previous_mtime = newest, -1
            elif selected is None:
                selected = args.status.resolve()
                previous_mtime = -1
            if selected is None:
                if time.monotonic()-last_wait_notice > 3:
                    print("WAIT agent_status.json — start the agent GUI and select the client PID", flush=True)
                    last_wait_notice = time.monotonic()
                if args.once:
                    return 2
                time.sleep(args.poll)
                continue
            try:
                mtime = selected.stat().st_mtime_ns
            except OSError:
                selected = None
                continue
            if mtime == previous_mtime:
                if args.once:
                    return 0
                time.sleep(args.poll)
                continue
            status = read_json(selected)
            if status is None:
                time.sleep(min(.05, args.poll))
                continue
            row = telemetry_row(status, time.monotonic()-telemetry_started)
            if row is not None:
                telemetry_writer.write(row)
            current = summarize(status)
            acceptance.update(current, status)
            changes = format_change(current, previous_summary)
            if changes:
                event = {"observed_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                         "status_path": str(selected), "summary": current, "changes": changes}
                event_writer.write(event)
                stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"\n[{stamp}] {selected.parent.name}", flush=True)
                for line in changes:
                    print("  " + line, flush=True)
            previous_summary, previous_mtime = current, mtime
            if args.once:
                return 0
            if args.duration and time.monotonic()-monitor_started >= args.duration:
                report = acceptance.report(ended_at=time.monotonic(), final_summary=current,
                                           final_status=status, required_duration=args.duration)
                report["status_path"] = str(selected)
                report_path = debug_dir / f"acceptance-{session_stamp}.json"
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"ACCEPTANCE {report_path} {report}", flush=True)
                return 0 if report["result"] == "PASS" else 3
            time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\nLive debugger stopped; no client input was sent.", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
