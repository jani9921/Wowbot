from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from collections import deque
from .bindings import BindingsCache
from .engine import AutonomousAgent
from .executor import InputExecutor
from .memory import AgentMemory
from .models import Mode
from .reasoner import OllamaReasoner
from .runtime_scheduler import RateMeter
from .runtime_control import (RuntimeControl, compact_fast_payload,
                              confirmed_quest_dialog)
from .runtime_diagnostics_phase import finalize_runtime_diagnostics
from .runtime_observation_phase import build_runtime_observations
from .runtime_perception_phase import update_runtime_perception
from .runtime_safety_phase import enforce_runtime_safety
# V4-083/V4-095: extracted verbatim to visual_recognition_stabilizer.py to
# reduce this file's size; re-exported here so every existing import path
# (including tests/test_agent_runtime.py's `from .runtime import
# _manual_mouseover_learning_probe, ...`) keeps working unchanged.
from .visual_recognition_stabilizer import (
    _VisualRecognitionStabilizer,
    _manual_mouseover_learning_probe,
    _publishable_visual_matches,
)
from .runtime_lifecycle import RuntimeLifecycleMixin
# Offline replay lives in offline_replay.py; re-exported for existing callers.
from .offline_replay import replay  # noqa: F401


def _project_addon_version() -> str | None:
    """Version of the repository addon the installer copies (toc, no suffix)."""
    from wowbot.install.checks import toc_version
    root = Path(__file__).resolve().parents[3]
    version = toc_version(root / "addon" / "AIPlayerControllerExport-12.1.0")
    return version.split("-")[0] if version else None


class AgentRuntime(RuntimeLifecycleMixin):
    """One selected PID, one agent, one input authority. Starts passive."""

    def __init__(self, pid: int, cache: Path, output: Path, *, ollama=None, sensor=None,
                 executor=None, vision=True, mmap_path=None, replay_path=None,
                 world3d_model=None):
        from .bindings import NoBindingsCache
        self.bindings = BindingsCache(cache) if cache else NoBindingsCache()
        self.executor = executor or InputExecutor(pid, self.bindings)
        self.output = output
        output.mkdir(parents=True, exist_ok=True)
        from .suppressed_errors import SuppressedErrors
        self.suppressed_errors = SuppressedErrors(Path(output) / "runtime_errors.log")
        self.expected_addon_version = _project_addon_version()
        # User 2026-10-03: learned memory belongs to the user, not to one WoW
        # process.  Per-PID folders keep only this run's logs/captures.
        from .profile_store import profile_directory
        self.profile = profile_directory(output)
        self.memory = AgentMemory(
            self.profile / "agent_memory.sqlite3",
            commit_interval_seconds=float(os.environ.get("AIPC_MEMORY_COMMIT_SECONDS", "1.0")),
            background_checkpoint_seconds=float(os.environ.get("AIPC_MEMORY_CHECKPOINT_SECONDS", "5.0")),
            relation_flush_interval_seconds=float(os.environ.get("AIPC_MEMORY_RELATION_FLUSH_SECONDS", "1.0")),
            async_writes=os.environ.get("AIPC_MEMORY_ASYNC_WRITES", "1").strip() != "0",
            cache_size_kib=32768)
        from .binding_inventory import BindingInventory
        self.binding_inventory = BindingInventory(output, self.bindings, pid)
        from .spatial_memory import SpatialMemory
        self.spatial = SpatialMemory(self.profile)
        self._visual_recognition_stabilizer = _VisualRecognitionStabilizer()
        self.reasoner = OllamaReasoner(ollama or {"enabled": False})
        self.agent = AutonomousAgent(self.executor, self.bindings, self.memory, self.reasoner,
                                     entity_memory=self.spatial.entities, navmesh=mmap_path)
        # Local-LLM text interpretation (quest text, ability tooltips, NPC
        # speech); asynchronous, cached per user, advisory only.
        from .semantic_advisor import SemanticAdvisor, load_semantic_config
        # User 2026-10-05: the quest-text interpreter follows its own setting
        # (config/ai_decision.json "semantic", env AIPC_SEMANTIC_ENABLED) and
        # runs whenever a local Ollama answers -- also from the GUI.  It is
        # asynchronous and backs off while Ollama is down.  Only the optional
        # Ollama *planner* advisor (`ollama`) stays an explicit opt-in.
        semantic_config = load_semantic_config()
        self.semantic = SemanticAdvisor(semantic_config, self.profile / "semantic_cache.json")
        self.agent.semantic_advisor = self.semantic
        # Per-quest visual prototypes survive restarts (per user profile).
        from .visual_prototypes import VisualPrototypeMemory
        self.agent.world.__dict__["visual_prototypes"] = VisualPrototypeMemory(
            self.profile / "visual_prototypes.json")
        # Quest givers/enders, objective creatures, how objectives advanced and
        # learned vehicle ability effects survive restarts (user 2026-10-05).
        from .quest_creature_memory import QuestCreatureMemory
        creature_memory = QuestCreatureMemory(self.profile / "quest_creature_memory.sqlite3")
        self.agent.world.__dict__["quest_creature_memory"] = creature_memory
        try:
            effects = self.agent.world.__dict__.setdefault("vehicle_ability_effects", {})
            for key, effect in creature_memory.ability_effects().items():
                effects.setdefault(key, effect)
        except Exception as error:
            self.suppressed_errors.report("load_vehicle_ability_effects", error)
        if hasattr(self.executor, "performance_monitor"):
            self.executor.performance_monitor = self.agent.performance_monitor
        # Creature types whose tooltip named an open quest survive restarts
        # (live 2026-10-03 13:42/13:47: a porcupine/goat selected before a
        # restart was never attacked).  Shared by every PID's output dir.
        self._quest_npcs_path = self.profile / "quest_relevant_npcs.json"
        from wowbot.navigation.entrance_verification import EntranceObserver
        self._entrance_observer = EntranceObserver(self.profile / "verified_entrances.jsonl")
        self._quest_npcs_saved = None
        try:
            loaded = json.loads(self._quest_npcs_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.agent.world.__dict__.setdefault("quest_relevant_npcs", {}).update(
                    {str(k): v for k, v in loaded.items() if isinstance(v, dict)})
                self._quest_npcs_saved = json.dumps(loaded, sort_keys=True)
        except (OSError, ValueError):
            pass
        restored_goal = self.memory.latest_active_goal()
        if restored_goal:
            self.agent.restore_goal(restored_goal, time.monotonic())
        self._capture_process_handle = None
        if sensor is None:
            from .capture_selection import build_default_sensor
            sensor, self._capture_process_handle = build_default_sensor(pid, self.executor.backend)
        self.sensor = sensor
        self.perception = None
        if vision:
            from .perception import PerceptionWorker
            from wowbot.vision.world3d.learned_detector import build_runtime_learned_detector
            learned_detector = build_runtime_learned_detector(
                world3d_model, capture_handle=self._capture_process_handle)
            if (callable(getattr(learned_detector, "set_trace_path", None))
                    and os.environ.get("AIPC_FEED_TRACE", "1").strip() != "0"):
                # Per-frame detector association record for offline replay.
                learned_detector.set_trace_path(output / "feed_association_trace.jsonl")
            live_vision_monitor = None
            if os.environ.get("AIPC_LIVE_VISION", "").strip().lower() in {
                    "1", "true", "yes", "on"}:
                from wowbot.diagnostics.live_vision_monitor import LiveVisionMonitor
                live_vision_monitor = LiveVisionMonitor(
                    maximum_hz=float(os.environ.get("AIPC_LIVE_VISION_HZ", "60")))
            self._live_vision_monitor = live_vision_monitor
            proposal_mode = os.environ.get("AIPC_WORLD3D_PROPOSAL_MODE", "YOLO_ONLY")
            if (os.environ.get("AIPC_WORLD3D_PROCESS", "1").strip() != "0"
                    and self._capture_process_handle is not None
                    and getattr(learned_detector, "capture_driven", False)):
                # World3D perception in its own process (own GIL): see
                # perception_process.py.  The feed pipeline is started here
                # because that process only holds a client endpoint.
                from .perception_process import ProcessPerceptionWorker
                learned_detector.start_pipeline(
                    proposal_mode=str(proposal_mode).strip().upper(),
                    tracker_mode=str(os.getenv("AIPC_WORLD3D_TRACKER", "AUTO"))
                    .strip().lower().replace("-", ""))
                self.perception = ProcessPerceptionWorker(
                    capture_ring=self._capture_process_handle.client.ring_name,
                    feed=learned_detector, live_vision_monitor=live_vision_monitor,
                    hard_example_directory=output / "vision-hard-examples",
                    proposal_mode=proposal_mode)
            else:
                self.perception = PerceptionWorker(
                    hard_example_directory=output / "vision-hard-examples",
                    scheduler=self.agent.brain_scheduler,
                    learned_detector=learned_detector,
                    live_vision_monitor=live_vision_monitor,
                    world3d_proposal_mode=proposal_mode)
        from .vision_dataset import AutoLabeledExampleCollector
        self.vision_dataset = AutoLabeledExampleCollector(output / "vision-dataset")
        from .map_marker_dataset import MapMarkerCropCollector
        # Map-marker YOLO dataset (World Map + minimap crops with addon facts).
        # AIPC_MAP_DATASET=0 disables it; writing happens off the agent step.
        self.map_marker_dataset = MapMarkerCropCollector(
            output / "map-marker-dataset"
            if os.environ.get("AIPC_MAP_DATASET", "1").strip().lower()
            not in {"0", "false", "no", "off"} else None)
        self.pid = pid
        self.stopped = threading.Event()
        self.thread = None
        self.status = {"mode": "MANUAL", "sensor": "waiting", "pid": pid}
        self.arm_at = None
        self.arm_deadline = None
        self.test_seconds = None
        self.test_deadline = None
        # A bounded GUI trial is normally a hard safety boundary.  There is
        # one narrow exception: if its last fresh addon packet has already
        # opened an explicit quest dialog, allow the current dialog click and
        # its authoritative verification to finish.  Without this, a trial
        # that reaches a quest giver near its deadline does the expensive
        # part (locate/approach/interact) then drops to MANUAL immediately
        # before the one safe, addon-confirmed ACCEPT/COMPLETE click.
        self.test_dialog_grace_deadline = None
        self._test_dialog_grace_enabled = False
        self._test_dialog_grace_used = False
        self.last_write = 0.
        self._last_notice = ""
        self.started = False
        self._semantic_seen = {}
        from .live_capture import LiveCaptureRecorder
        # 180 frames cover only ~5 min of a trial; long unattended trials
        # raise the limit with AIPC_LIVE_CAPTURE_MAX_FRAMES.
        self.live_capture = LiveCaptureRecorder(
            output, max_frames=int(os.environ.get("AIPC_LIVE_CAPTURE_MAX_FRAMES") or 180))
        from .cross_view import CrossViewResolver
        self.cross_view = CrossViewResolver()
        self._control = RuntimeControl(self)
        self.control_hz = 40.0
        self._runtime_rate = RateMeter(10.)
        self._fast_control_consumed_rate = RateMeter(10.)
        self._payload_rate = RateMeter(30.)
        self._fast_payload_rate = RateMeter(10.)
        self._full_payload_rate = RateMeter(30.)
        self._step_latencies = deque(maxlen=240)
        self._next_maintenance = time.monotonic()+60.
        self._maintenance_status = {"status": "scheduled"}
        self._last_control_vision_revision = -1
        self._last_published_vision_revision = -1
        self._status_write_ms = 0.0
        self._status_write_error = None
        self._status_write_lock = threading.Lock()
        self._status_write_pending = None
        self._status_write_event = threading.Event()
        self._status_write_stop = threading.Event()
        self._status_writer_thread = None
        self._not_foreground_since: float | None = None
        self._foreground_suspended = False
        self._arm_blockers: tuple[str, ...] = ()
        # sensor_diagnostics (polls/updates/poll_ms) only reflects the
        # background BufferedPixelSensor thread's own capture+decode loop --
        # it stays healthy even when the MAIN thread's mailbox consumption
        # (this poll() call) stalls for seconds. Live-confirmed 2026-09-12:
        # a 5.6s receive_gap with fully healthy background polls/updates the
        # whole time, meaning the freeze is in the hand-off, not capture.
        # Tracks that hand-off from the main thread's own point of view.
        self._poll_none_streak = 0
        self._last_payload_at: float | None = None
        # Planner/world fusion is intentionally slower than the physical
        # movement servo.  Fresh FAST packets can update the one canonical
        # NavigationService between these medium-loop boundaries.
        # Planner/WorldModel cadence.  The master architecture assigns the
        # planner a 1--3 Hz role; physical movement feedback is handled by
        # the independent fast lane above.  Keeping this at 3 Hz prevents a
        # CPU-heavy vision/world tick from immediately consuming the whole
        # interval before the next FAST movement sample can run.
        self.medium_hz = 3.0
        self._next_medium_at = 0.0
        configured_replay = str(replay_path or os.environ.get("AIPC_REPLAY_PATH", "")).strip()
        if configured_replay:
            from wowbot.diagnostics import RuntimeReplayBridge
            self.replay_bridge = RuntimeReplayBridge(Path(configured_replay))
        else:
            self.replay_bridge = None

    def goal(self, text, parameters=None):
        self._control.goal(text, parameters)

    @staticmethod
    def _compact_fast_payload(payload: dict) -> dict:
        return compact_fast_payload(payload)

    def _addon_version_mismatch(self) -> str | None:
        """Running addon version when it differs from the project's, else None.

        Every AIPC5 full state carries ``addon_version``; it is absent only in
        synthetic states, which therefore do not block.
        """
        expected = self.expected_addon_version
        running = self.agent.world.state.get("addon_version")
        if not expected or running is None:
            return None
        base = str(running).split("-")[0]
        return None if base == expected else str(running)

    def _binding_preflight(self):
        domain = self.agent.goal.domain if self.agent.goal else "UNKNOWN"
        actionbar = self.agent.world.state.get("actionbar", [])
        static = self.bindings.preflight(domain, actionbar)
        live = self.binding_inventory.validate_actions(
            self.bindings.required_actions(domain, actionbar))
        return {**static, "ready": static["ready"] and live["ready"],
                "client_validation": live,
                "binding_mismatches": live["mismatches"],
                "unverified_bindings": live["unverified"]}

    def mode(self, mode):
        self._control.mode(mode)

    def test_step(self, *, actions=1, seconds=30):
        self._control.test_step(actions=actions, seconds=seconds)

    @staticmethod
    def _confirmed_quest_dialog(payload: dict | None, world_state: dict | None) -> bool:
        return confirmed_quest_dialog(payload, world_state)

    def step(self, now):
        started_at = time.perf_counter()
        self._runtime_rate.mark(now)
        backend = getattr(self.executor, "backend", None)
        enforce_runtime_safety(self, backend, now)
        payload = self.sensor.poll(now)
        if payload is not None:
            payload = self._compact_fast_payload(payload)
            self._payload_rate.mark(now)
            self._poll_none_streak = 0
            self._last_payload_at = now
            if payload.get("transport_kind") == "FAST":
                self._fast_payload_rate.mark(now)
            else:
                self._full_payload_rate.mark(now)
        else:
            self._poll_none_streak += 1
        supplemental = []
        sensor_ms = (time.perf_counter()-started_at)*1000
        phase_started = time.perf_counter()
        # Capture/initial grid discovery may take time; never use its start time as now.
        current = time.monotonic() if self.started else now
        if self.agent.mode == Mode.FULL_AI and self._foreground_suspended:
            # Foreground is an execution-authority prerequisite, not merely
            # another observation.  Do not let a still-fresh pre-Alt-Tab
            # WorldModel launch TARGET/INTERACT/etc. only for the backend to
            # reject it and turn a harmless focus transition into MANUAL.
            # The selected-PID gate above has already released movement.
            self.agent.last_decision = {
                "skill": "WAIT",
                "reason": "selected_pid_foreground_suspended",
                "input_authority": "REVOKED",
                "foreground_missing_for": round(
                    max(0., current-(self._not_foreground_since or current)), 3),
            }
            result = self.agent.status(current)
            return finalize_runtime_diagnostics(
                self, result, current=current, started_at=started_at,
                sensor_ms=sensor_ms, perception_ms=0., observations_ms=0.,
                tick_ms=0., backend=backend)
        # Pump the passive tracker before the FAST movement lane can return.
        # Previously every fresh movement packet skipped perception entirely,
        # so the 30 Hz capture/control path paradoxically starved World3D to
        # the 3 Hz medium planner cadence.  This call only schedules/harvests
        # bounded latest-frame vision; no input or planning authority moves
        # into perception.
        visual_candidates = update_runtime_perception(self, payload, current)
        perception_ms = (time.perf_counter()-phase_started)*1000
        fast_control = None
        if (payload is not None and payload.get("transport_kind") == "FAST"
                and self.agent.mode == Mode.FULL_AI and self.agent.pending is not None
                and self.agent.pending.proposal.skill in {
                    "MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION"}):
            try:
                fast_control = self.agent.fast_movement_control(payload, current)
            except Exception as error:
                # Preserve the existing fail-closed boundary.  The medium
                # tick below records/projects the failure; no hidden fast-loop
                # exception may leave a held key behind.
                self.executor.stop()
                self.agent.set_mode(Mode.MANUAL)
                self.agent.last_result = {
                    "outcome": "FAILURE", "skill": "MOVE",
                    "reason": f"fast_control_error:{type(error).__name__}:{error}",
                }
                fast_control = {"consumed": False, "force_medium": True,
                                "reason": "fast_control_error"}
            if fast_control.get("consumed"):
                self._fast_control_consumed_rate.mark(current)
            medium_due = current >= self._next_medium_at
            deadline_due = (
                self.test_dialog_grace_deadline is not None
                and current >= self.test_dialog_grace_deadline
                or self.test_deadline is not None and current >= self.test_deadline)
            if (not medium_due and not deadline_due
                    and not fast_control.get("terminal")
                    and not fast_control.get("force_medium")):
                # High-rate control lane: no vision fusion, planner, SQLite,
                # status serialization or GUI file write.  The watchdog still
                # bounds every lease and the same selected-PID executor checks
                # focus immediately before each refresh.
                return self.status
        elif (payload is None and self.agent.mode == Mode.FULL_AI
                and self.agent.pending is not None
                and self.agent.pending.proposal.skill in {
                    "MOVE", "FOLLOW", "REACH_OBJECT", "REACH_LOCATION"}
                and current < self._next_medium_at
                and not (self.test_deadline is not None and current >= self.test_deadline)
                and not (self.test_dialog_grace_deadline is not None
                         and current >= self.test_dialog_grace_deadline)):
            # An empty poll between FAST packets is not a medium-tick slot:
            # running one here re-armed the 1 s reach window every time, so
            # the medium tick never landed on a packet (live 2026-10-04).
            return self.status
        # Vision runs at its own cadence over the latest selected-client frame.
        # Pixel telemetry is paged and can be much slower than screen capture.
        # Perception therefore runs independently. Ordinary planning projections
        # remain correlated with complete addon snapshots; an active persistent
        # VisualApproach also receives fresh WORLD3D-only control observations.
        phase_started = time.perf_counter()
        if payload and payload.get("transport_kind") != "FAST":
            self.binding_inventory.ingest(payload, current)
            live_bindings = self._binding_preflight()
            if (self.agent.mode == Mode.FULL_AI
                    and live_bindings["binding_mismatches"]):
                self.mode("MANUAL")
                self.agent.last_result = {
                    "outcome": "CANCELLED",
                    "reason": "Az élő kliens bindingje eltér a kiválasztott cache-től.",
                    "binding_mismatches": live_bindings["binding_mismatches"],
                }
        observation_batch = build_runtime_observations(
            self, payload, current, visual_candidates)
        base_observation = observation_batch.base
        supplemental = list(observation_batch.supplemental)
        observations_ms = (time.perf_counter()-phase_started)*1000
        if self.replay_bridge is not None:
            if payload is not None:
                self.replay_bridge.record_observation(base_observation)
            for observation in supplemental:
                self.replay_bridge.record_observation(observation)
        phase_started = time.perf_counter()
        if self.arm_at is not None and current >= self.arm_at:
            # Use the newly received observation, not the stale pre-focus state.
            self.agent.tick(payload, current, tuple(supplemental))
            payload = None
            supplemental = []
            vision_ready = not self.perception or self.perception.ready_for_action(current)
            binding_preflight = self._binding_preflight()
            foreground_ready = not backend or backend.is_selected_foreground()
            fresh_ready = self.agent.world.fresh(current)
            blockers = []
            if not foreground_ready:
                blockers.append("waiting_for_selected_pid_focus")
            if not fresh_ready:
                blockers.append("waiting_for_fresh_addon_state")
            if not vision_ready:
                blockers.append("waiting_for_recent_world3d_frame")
            detector_ready = getattr(self.perception, "detector_ready", None)
            detector_warm = not callable(detector_ready) or detector_ready(current)
            if not detector_warm:
                # Live 2026-09-30: FULL_AI searched blind during the ~20 s
                # TensorRT warm-up and exhausted its scan sectors.
                blockers.append("waiting_for_world3d_detector")
            if binding_preflight["unverified_bindings"]:
                blockers.append("waiting_for_binding_export_pages")
            self._arm_blockers = tuple(blockers)
            if self.agent.world.fresh(current) and binding_preflight["missing"]:
                # The click-time check may have seen an empty/stale actionbar.
                # Only the freshly ingested state can prove that every action
                # the selected client may need exists in the selected cache.
                self.arm_at = self.arm_deadline = None
                self._arm_blockers = ()
                self.agent.last_result = {
                    "outcome": "CANCELLED",
                    "reason": "Start elutasítva: hiányzó bindingok a kiválasztott cache-ben: "
                              + ", ".join(binding_preflight["missing"]),
                    "missing_bindings": binding_preflight["missing"],
                }
            elif (self.agent.world.fresh(current)
                    and binding_preflight["binding_mismatches"]):
                self.arm_at = self.arm_deadline = None
                self._arm_blockers = ()
                self.agent.last_result = {
                    "outcome": "CANCELLED",
                    "reason": "Start elutasítva: az élő kliens bindingje eltér a kiválasztott cache-től.",
                    "binding_mismatches": binding_preflight["binding_mismatches"],
                }
            elif (self.agent.world.fresh(current)
                    and (running_addon := self._addon_version_mismatch()) is not None):
                # Issue #32: an updated project addon without /reload keeps the
                # old addon running; its missing features surface as unrelated
                # symptoms (stale state, INSPECT failures) mid-run.
                self.arm_at = self.arm_deadline = None
                self._arm_blockers = ()
                self.agent.last_result = {
                    "outcome": "CANCELLED",
                    "reason": (f"Start elutasítva: a futó addon {running_addon or '?'}, a projekté "
                               f"{self.expected_addon_version}; telepítsd az addont és /reload."),
                    "addon_version_mismatch": {"running": running_addon,
                                               "expected": self.expected_addon_version},
                }
            elif (self.agent.world.fresh(current)
                    and binding_preflight["unverified_bindings"]):
                # Catalog pages arrive incrementally. Stay passive until every
                # required non-control action has exact client evidence.
                pass
            elif (self.agent.world.fresh(current)
                    and (not backend or backend.is_selected_foreground())
                    and vision_ready and detector_warm):
                self.arm_at = self.arm_deadline = None
                self._arm_blockers = ()
                self.agent.set_mode(Mode.FULL_AI)
                if self.test_seconds is not None:
                    self.test_deadline = current+self.test_seconds
            elif self.arm_deadline is None or current >= self.arm_deadline:
                self.arm_at = self.arm_deadline = None
                timed_out_on = self._arm_blockers
                self._arm_blockers = ()
                self.agent.last_result = {
                    "outcome": "CANCELLED",
                    "reason": "Start elutasítva: az indítási kézfogás időtúllépett ("
                              + ", ".join(timed_out_on or ("unknown",)) + ")",
                    "start_blockers": list(timed_out_on),
                }
        if self.test_dialog_grace_deadline is not None and current >= self.test_dialog_grace_deadline:
            self.mode("MANUAL")
            self.agent.last_result = {
                "outcome": "CANCELLED",
                "reason": "bounded_live_test_dialog_grace_expired",
            }
        elif self.test_deadline is not None and current >= self.test_deadline:
            if (self._test_dialog_grace_enabled and not self._test_dialog_grace_used
                    and self._confirmed_quest_dialog(payload, self.agent.world.state)):
                # One short transaction window is enough for planner ->
                # QUEST_DIALOG -> verifier.  It is intentionally not a
                # general test-time extension and cannot be reached without
                # exact addon action coordinates.
                self.test_deadline = None
                self._test_dialog_grace_used = True
                self.test_dialog_grace_deadline = current+5.
            else:
                self.mode("MANUAL")
                self.agent.last_result = {"outcome": "CANCELLED", "reason": "bounded_live_test_timeout"}
        # Perf fix (live-confirmed 2026-09-22): tick() can call AgentMemory
        # many times (one _record() per queued event/skill-lifecycle
        # transition). Batch them into one commit instead of one per call.
        with self.memory.batch():
            result = self.agent.tick(payload, current, tuple(supplemental))
        try:
            from .semantic_advisor import update_world
            update_world(self.semantic, self.agent.world, current)
        except Exception as error:
            self.semantic.metrics["last_error"] = f"update:{type(error).__name__}: {error}"[:200]
        prototypes = self.agent.world.__dict__.get("visual_prototypes")
        if prototypes is not None:
            prototypes.save(current)
        self._save_ability_effects(current)
        self._publish_navigation_overlay(current)
        try:
            self._entrance_observer.observe(self.agent.world.state, current)
        except Exception as error:
            self.suppressed_errors.report("entrance_observer", error)
        if self.replay_bridge is not None:
            self.replay_bridge.record_world_delta(self.agent.world)
        if self.test_dialog_grace_deadline is not None:
            terminal = result.get("result") or {}
            if (terminal.get("skill") in {"QUEST_DIALOG", "FIELD_TURN_IN"}
                    and terminal.get("outcome") in {"SUCCESS", "FAILURE", "CANCELLED"}):
                # The grace is only for the dialog transaction, never for
                # another planning cycle after it.  Leave the result intact
                # so the user can see whether acceptance was verified.
                self.mode("MANUAL")
                result["mode"] = "MANUAL"
                result["test_dialog_grace"] = "quest_dialog_terminal"
        tick_ms = (time.perf_counter()-phase_started)*1000
        return finalize_runtime_diagnostics(
            self, result, current=current, started_at=started_at,
            sensor_ms=sensor_ms, perception_ms=perception_ms,
            observations_ms=observations_ms, tick_ms=tick_ms,
            backend=backend)
