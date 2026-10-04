"""Bounded screenshots of the already-authorized selected WoW client frame."""
from __future__ import annotations

from datetime import datetime
from collections import deque
import json
import os
from pathlib import Path
import shutil
import threading
import time


class LiveCaptureRecorder:
    """Record client-only frames at meaningful state changes.

    This consumes the same foreground selected-PID frame already captured by
    PixelSensor. It never captures the desktop, opens another process, or sends
    input. Disk work runs on one background worker so the control loop cannot
    stall while JPEG encoding is in progress.
    """

    def __init__(self, output: Path, *, heartbeat: float = 2.0,
                 min_interval: float = .5, max_frames: int = 180,
                 keep_segments: int | None = None) -> None:
        self.output = output
        # User 2026-10-04: the captures filled the disk.  Only the newest
        # runs' segments (all PIDs of this output tree) are kept.
        self.keep_segments = max(1, int(keep_segments if keep_segments is not None
                                        else os.environ.get("AIPC_LIVE_CAPTURE_KEEP") or 3))
        self.prune_thread: threading.Thread | None = None
        self.created: dict[Path, float] = {}
        self.heartbeat = float(heartbeat)
        self.min_interval = float(min_interval)
        self.max_frames = int(max_frames)
        self.lock = threading.Lock()
        self.worker: threading.Thread | None = None
        # One item may still be encoding when FULL_AI starts a new segment.
        # A two-slot queue lets rotate() remain non-blocking while preserving
        # both the old segment's final frame and the new segment's first one.
        self.pending = deque(maxlen=2)
        self.segment = 0
        self._new_segment()

    def _new_segment(self) -> None:
        self.segment += 1
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        self.directory = self.output / "live-captures" / f"{stamp}-{self.segment:03d}"
        # Protected before it exists, so a pruner that lists it already knows it.
        now = time.monotonic()
        self.created = {path: at for path, at in self.created.items() if now-at <= 120.}
        self.created[self.directory] = now
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest = self.directory / "manifest.jsonl"
        self.last_capture = -1e9
        self.last_signature = None
        self.count = 0
        self.dropped = 0
        self.prune_thread = threading.Thread(target=self._prune_old_segments, daemon=True,
                                             name="aipc-live-capture-prune")
        self.prune_thread.start()

    def _prune_old_segments(self) -> None:
        """Delete all but the newest ``keep_segments`` capture runs.

        Scope: this output's ``live-captures`` and its ``pid-*`` siblings'
        (the per-PID run folders of one output tree) -- nothing else.
        Segment names start with their timestamp, so name order is age order
        across PIDs.  Segments this recorder made in the last two minutes may
        still be encoding and are never touched.
        """
        own = self.output / "live-captures"
        try:
            roots = {own, *(path for path in self.output.parent.glob("pid-*/live-captures"))}
            listed = [path for root in roots if root.is_dir() for path in root.iterdir() if path.is_dir()]
        except OSError:
            return
        # Read *after* listing: every segment this recorder made before the
        # listing is registered (see _new_segment), even one from a rotate()
        # that ran after this thread started.
        with self.lock:
            protected = frozenset(self.created)
        segments = [path for path in listed if path not in protected]
        segments.sort(key=lambda path: path.name, reverse=True)
        with_frames = [path for path in segments if next(path.glob("*.jpg"), None) is not None]
        keep = set(with_frames[:max(0, self.keep_segments-len(protected))])
        for path in segments:
            if path not in keep:
                shutil.rmtree(path, ignore_errors=True)

    def rotate(self) -> None:
        """Start a fresh bounded capture segment for every requested live run."""
        with self.lock:
            self._new_segment()

    @staticmethod
    def _summary(status: dict) -> dict:
        world = status.get("world") if isinstance(status.get("world"), dict) else {}
        player = world.get("player") if isinstance(world.get("player"), dict) else {}
        loop = status.get("autonomous_loop") if isinstance(status.get("autonomous_loop"), dict) else {}
        movement = status.get("movement_controller") if isinstance(status.get("movement_controller"), dict) else {}
        seek = status.get("vision_seek") if isinstance(status.get("vision_seek"), dict) else {}
        vision = status.get("vision_diagnostics") if isinstance(status.get("vision_diagnostics"), dict) else {}
        world_lane = vision.get("world") if isinstance(vision.get("world"), dict) else {}
        v2 = vision.get("world3d_v2") if isinstance(vision.get("world3d_v2"), dict) else {}
        decision = status.get("decision") if isinstance(status.get("decision"), dict) else {}
        result = status.get("result") if isinstance(status.get("result"), dict) else {}
        return {
            "pid": status.get("pid"), "mode": status.get("mode"), "sensor": status.get("sensor"),
            "session_id": world.get("session_id"), "fresh": world.get("fresh"),
            "map_id": player.get("map_id"), "position": player.get("position"),
            "target": player.get("target"), "active_quests": player.get("active_quests"),
            "decision": {"skill": decision.get("skill"), "reason": decision.get("reason")},
            "result": {key: result.get(key) for key in ("outcome", "skill", "reason", "failure_type", "action_id")},
            "phase": loop.get("phase"), "commitment": loop.get("commitment"),
            "movement": {key: movement.get(key) for key in
                         ("phase", "progress_state", "stuck_belief", "no_progress_count", "reason")},
            "vision_seek": {key: seek.get(key) for key in
                            ("phase", "target_track_id", "candidate_score", "last_x",
                             "last_bbox_height", "scan_index", "control_updates",
                             "forward_updates", "camera_updates",
                             "player_turn_updates")},
            "vision": {"status": world_lane.get("status"), "duration_ms": world_lane.get("duration_ms"),
                       "candidates": world_lane.get("candidates"),
                       "camera_motion_px": v2.get("camera_motion_px"),
                       "generic_candidates": v2.get("generic_candidates"),
                       "output_candidates": v2.get("output_candidates")},
            "runtime_error": status.get("runtime_error"),
        }

    @staticmethod
    def _event_signature(summary: dict) -> str:
        changing = {key: summary.get(key) for key in
                    ("mode", "sensor", "session_id", "decision", "result", "phase", "commitment",
                     "movement", "vision_seek", "runtime_error")}
        return json.dumps(changing, sort_keys=True, ensure_ascii=False, default=str)

    def consider(self, frame, status: dict, now: float) -> bool:
        if frame is None or self.count >= self.max_frames:
            return False
        raw, width, height = frame
        if len(raw) != width*height*4 or width < 320 or height < 200:
            return False
        summary = self._summary(status)
        signature = self._event_signature(summary)
        changed = signature != self.last_signature
        heartbeat_due = now-self.last_capture >= self.heartbeat
        critical = bool(summary.get("runtime_error")) or summary.get("result", {}).get("outcome") in {"FAILURE", "CANCELLED"}
        if not (changed or heartbeat_due or critical) or now-self.last_capture < self.min_interval:
            return False
        with self.lock:
            if len(self.pending) >= self.pending.maxlen:
                self.dropped += 1
                return False
            self.count += 1
            index = self.count
            reason = "critical" if critical else "state_change" if changed else "heartbeat"
            # Bind paths now. rotate() may switch self.directory while this
            # item is being encoded on the worker.
            self.pending.append((bytes(raw), int(width), int(height), summary,
                                 now, index, reason, self.directory, self.manifest))
            self.last_capture, self.last_signature = now, signature
            if self.worker is None or not self.worker.is_alive():
                self.worker = threading.Thread(target=self._drain, name="aipc-live-capture", daemon=True)
                self.worker.start()
        return True

    def _drain(self) -> None:
        while True:
            with self.lock:
                item = self.pending.popleft() if self.pending else None
            if item is None:
                return
            raw, width, height, summary, observed, index, reason, directory, manifest = item
            stamp = datetime.now().strftime("%H%M%S-%f")[:-3]
            name = f"{index:04d}-{stamp}-{reason}.jpg"
            path = directory / name
            try:
                from PIL import Image
                image = Image.frombytes("RGBA", (width, height), raw, "raw", "BGRA")
                image.convert("RGB").save(path, "JPEG", quality=90, optimize=False)
                event = {"frame": name, "observed_monotonic": observed,
                         "saved_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                         "reason": reason, "width": width, "height": height, "summary": summary}
                with manifest.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str)+"\n")
            except Exception as error:
                with manifest.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"frame": name, "reason": "capture_error",
                        "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False)+"\n")

    def close(self) -> None:
        worker = self.worker
        if worker and worker.is_alive():
            worker.join(timeout=3)

    def diagnostics(self) -> dict:
        return {"directory": str(self.directory), "frames": self.count,
                "dropped": self.dropped, "max_frames": self.max_frames,
                "heartbeat_seconds": self.heartbeat, "segment": self.segment}
