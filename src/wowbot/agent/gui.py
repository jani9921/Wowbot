from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .runtime import AgentRuntime


def dashboard_projection(state: dict, model_path=None) -> dict[str, str]:
    """Small read-only view of the agent's actual status, never GUI-owned truth."""
    world = state.get("world") if isinstance(state.get("world"), dict) else {}
    player = world.get("player") if isinstance(world.get("player"), dict) else {}
    quests = [item for item in player.get("active_quests") or [] if isinstance(item, dict)]
    quest = next((item for item in quests if not item.get("is_complete")),
                 quests[0] if quests else {})
    objectives = [item for item in quest.get("objectives") or [] if isinstance(item, dict)]
    objective = next((item for item in objectives if not item.get("is_complete")),
                     objectives[0] if objectives else {})
    target = player.get("target") if isinstance(player.get("target"), dict) else {}
    decision = state.get("decision") if isinstance(state.get("decision"), dict) else {}
    rates = state.get("loop_rates") if isinstance(state.get("loop_rates"), dict) else {}
    reasoner = state.get("reasoner") if isinstance(state.get("reasoner"), dict) else {}
    semantic = (state.get("semantic_advisor")
                if isinstance(state.get("semantic_advisor"), dict) else {})
    detector_hz = rates.get("world_detector_hz")
    detector = f"{detector_hz:.1f} Hz" if isinstance(detector_hz, (int, float)) else "—"
    backend = Path(model_path).suffix.lower().lstrip(".").upper() if model_path else "—"
    return {
        "quest": f"Küldetés: {quest.get('title') or '—'} | Feladat: {objective.get('description') or '—'}",
        "control": (f"Döntés: {decision.get('skill') or '—'} | Célpont: "
                    f"{target.get('name') or '—'} | Detektor: {detector} ({backend})"),
        "advisor": (f"Ollama planner: {reasoner.get('status') or '—'} | "
                    f"szövegértelmező: {semantic.get('status') or '—'}"),
    }


class AgentWindow:
    def __init__(self, root, output: Path, *, auto_full_ai: bool = False):
        self.root, self.output, self.runtime = root, output, None
        root.title("AIPC Agent — Retail 12.1")
        root.geometry("1120x820")
        self.pid = tk.StringVar()
        self.cache = tk.StringVar()
        self.mmap_path = tk.StringVar()
        self.goal_text = tk.StringVar(value="Questelj az Exile's Reach szigeten")
        self._model_path = None
        self.summary = tk.StringVar(value="MANUAL — nincs kliens csatlakoztatva")
        self.quest_summary = tk.StringVar(value="Küldetés: — | Feladat: —")
        self.control_summary = tk.StringVar(value="Döntés: — | Célpont: — | Detektor: —")
        self.advisor_summary = tk.StringVar(value="Ollama: kikapcsolva")
        self._detail_json = None
        self._detail_trigger = None
        self._detail_rendered_at = -float("inf")
        # Runtime construction opens the large memory databases and builds the
        # telemetry/navmesh/perception chain.  It must never run in Tk's event
        # loop or Windows will report the GUI as hung during connection.
        self._connect_thread = None
        self._connect_results = queue.SimpleQueue()
        self._connect_generation = 0
        self._connect_started_at = None
        self._control_thread = None
        self._control_results = queue.SimpleQueue()
        self._control_started_at = None
        self._control_label = None
        self._closing = False
        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Kliens PID (nincs automatikus helyettesítés):").grid(row=0, column=0, sticky="w")
        self.pid_box = ttk.Combobox(outer, textvariable=self.pid, width=18)
        self.pid_box.grid(row=0, column=1, sticky="ew")
        ttk.Button(outer, text="PID-lista frissítése", command=self.refresh_pids).grid(row=0, column=2)
        ttk.Label(outer, text="Kiválasztott bindings-cache.wtf:").grid(row=1, column=0, sticky="w")
        ttk.Entry(outer, textvariable=self.cache).grid(row=1, column=1, sticky="ew")
        ttk.Button(outer, text="Tallózás", command=self.browse).grid(row=1, column=2)
        export_bar = ttk.Frame(outer)
        export_bar.grid(row=11, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Button(export_bar, text="Controller-cache létrehozása exportból", command=lambda: self.guard(self.export_cache)).pack(side="left")
        self.inventory_summary = tk.StringVar(value="Binding-export: még nincs adat")
        ttk.Label(export_bar, textvariable=self.inventory_summary).pack(side="left", padx=8)
        ttk.Label(outer, text=r"TrinityCore mmaps mappa (_retail_\mmaps):").grid(row=2, column=0, sticky="w")
        ttk.Entry(outer, textvariable=self.mmap_path).grid(row=2, column=1, sticky="ew")
        ttk.Button(outer, text="mmap tallózás", command=self.browse_mmap).grid(row=2, column=2)
        ttk.Label(outer, text="Magas szintű cél:").grid(row=3, column=0, sticky="w")
        ttk.Entry(outer, textvariable=self.goal_text).grid(row=3, column=1, columnspan=2, sticky="ew")
        ttk.Label(outer, text="Opcionális célparaméterek JSON (destination, target_npc_ids, mount_binding):").grid(row=5, column=0, columnspan=3, sticky="w")
        self.parameters = ttk.Entry(outer)
        self.parameters.insert(0, "{}")
        self.parameters.grid(row=6, column=0, columnspan=3, sticky="ew")
        buttons = ttk.Frame(outer)
        buttons.grid(row=7, column=0, columnspan=3, sticky="ew", pady=10)
        for label, callback in [("Csatlakozás / cache betöltése", self.connect), ("Cél alkalmazása", self.set_goal),
                                ("ASSIST — csak terv", lambda: self.mode("ASSIST")),
                                ("FULL_AI — biztonságos indítás", lambda: self.mode("FULL_AI")),
                                ("1 tesztlépés (5 mp)", self.test_step),
                                ("30 mp próba", self.test_run),
                                ("MANUAL / STOP", lambda: self.mode("MANUAL"))]:
            ttk.Button(buttons, text=label, command=lambda fn=callback: self.guard(fn)).pack(side="left", padx=3)
        ttk.Label(outer, textvariable=self.summary, wraplength=1000).grid(row=8, column=0, columnspan=3, sticky="w")
        dashboard = ttk.Frame(outer)
        dashboard.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(4, 2))
        for value in (self.quest_summary, self.control_summary, self.advisor_summary):
            ttk.Label(dashboard, textvariable=value, wraplength=1050).pack(anchor="w")
        ttk.Label(outer, text="FULL_AI után válts a kiválasztott WoW ablakra; az agent legfeljebb 45 mp-ig passzívan vár a fókusz + friss AIPC5 + vision kézfogásra.\nF12 → MANUAL. Rövid fókusz- vagy telemetry-kimaradás alatt minden input leáll, majd stabil adat után automatikusan folytatódik.").grid(row=10, column=0, columnspan=3, sticky="w", pady=8)
        self.detail = tk.Text(outer, wrap="word", font=("Consolas", 10))
        self.detail.grid(row=11, column=0, columnspan=3, sticky="nsew")
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(11, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.restore()
        if auto_full_ai:
            root.after(100, lambda: self.guard(self.connect_and_arm_full_ai))
        root.after(250, self.update)

    def guard(self, fn):
        try:
            fn()
        except Exception as error:
            messagebox.showerror("AIPC", str(error), parent=self.root)

    def refresh_pids(self):
        from tools.wow_window import find_visible_wow_windows
        self.pid_box["values"] = [str(w.pid) for w in find_visible_wow_windows()]

    def browse(self):
        path = filedialog.askopenfilename(title="Pontosan az alkalmazandó bindings-cache.wtf", filetypes=[("WoW bindings", "*.wtf"), ("Minden fájl", "*.*")])
        if path:
            self.cache.set(path)

    def browse_mmap(self):
        # User 2026-10-02: maps/vmaps/mmaps come from the extractors in _retail_;
        # the mmaps folder is read directly (a zip still loads if typed in).
        path = filedialog.askdirectory(title="TrinityCore mmaps mappa kiválasztása")
        if path:
            self.mmap_path.set(path)

    def restore(self):
        path = self.output / "agent_gui.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.cache.set(data.get("bindings_cache", ""))
                self.mmap_path.set(data.get("mmap_path", ""))
                self.goal_text.set(data.get("goal", self.goal_text.get()))
            except (ValueError, OSError):
                pass
        if not self.mmap_path.get().strip():
            configured = os.getenv("WOWBOT_MMAP_PATH", "").strip()
            world_data = os.getenv("WOWBOT_WORLD_DATA_PATH", "").strip()
            retail = Path(world_data) if world_data else Path(r"C:\Program Files (x86)\World of Warcraft\_retail_")
            candidate = Path(configured) if configured else retail / "mmaps"
            if candidate.is_file() or candidate.is_dir():
                self.mmap_path.set(str(candidate))
        # Never restore a PID or execution mode from a previous process session.

    def export_cache(self):
        import time
        from .binding_inventory import create_controller_cache
        from .models import Mode
        if not self.runtime:
            raise ValueError("Előbb csatlakozz MANUAL módban; várd meg a teljes binding-exportot.")
        runtime = self.runtime
        with runtime.agent.lock:
            if runtime.agent.mode != Mode.MANUAL or runtime.arm_at is not None or runtime.agent.pending is not None:
                raise ValueError("Cache-generálás előtt állítsd MANUAL módba, és töröld az időzített indítást.")
            if int(self.pid.get()) != runtime.pid:
                raise ValueError("A beírt PID eltér a csatlakoztatott klienstől; csatlakozz újra.")
            state = runtime.agent.world.state
            path = create_controller_cache(runtime.binding_inventory.report, runtime.output,
                pid=runtime.pid, session_id=state.get("session_id"), character_guid=state.get("character_guid"), now=time.monotonic())
        if messagebox.askyesno("Controller-cache elkészült", f"Új fájl:\n{path}\n\nAz eredeti fájl változatlan. Kiválasztod ezt a GUI-ban?\nA használathoz utána kattints: Csatlakozás / cache betöltése.", parent=self.root):
            self.cache.set(str(path))

    def connect(self, *, auto_arm=False):
        if self._connect_thread is not None and self._connect_thread.is_alive():
            raise ValueError("A csatlakozás már folyamatban van")
        pid = int(self.pid.get())
        # Empty field = export-only session (fresh PC): no key input, no
        # FULL_AI, only telemetry + binding export to create a cache.
        cache = Path(self.cache.get()) if self.cache.get().strip() else None
        from tools.wow_window import find_visible_wow_windows
        if not any(w.pid == pid for w in find_visible_wow_windows()):
            raise ValueError("A kiválasztott PID-hez nem található látható WoW ablak")
        mmap_path = Path(self.mmap_path.get()) if self.mmap_path.get().strip() else None
        from wowbot.vision.world3d.learned_detector import default_runtime_model_path
        world3d_model = default_runtime_model_path()
        parameters = json.loads(self.parameters.get() or "{}")
        if not isinstance(parameters, dict):
            raise ValueError("A célparaméterek JSON objektumot várnak")
        config = {
            "pid": pid, "cache": cache, "mmap_path": mmap_path,
            "world3d_model": world3d_model,
            "ollama": {"enabled": False},
            "goal": self.goal_text.get(), "parameters": parameters,
            "auto_arm": bool(auto_arm),
        }
        previous_runtime = self.runtime
        if previous_runtime is not None:
            # Reconnect revokes input immediately; the potentially slow joins,
            # database closes and new telemetry startup remain in the worker.
            previous_runtime.mode("MANUAL")
        self.runtime = None
        self._connect_generation += 1
        generation = self._connect_generation
        self._connect_started_at = time.monotonic()
        self.summary.set(f"PID {pid} | csatlakozás folyamatban — telemetry/runtime inicializálás…")
        self._connect_thread = threading.Thread(
            target=self._connect_worker,
            args=(generation, config, previous_runtime),
            name="aipc-gui-connect", daemon=True)
        self._connect_thread.start()

    def _connect_worker(self, generation, config, previous_runtime):
        """Build/start a runtime without touching any Tk object."""
        runtime = None
        try:
            if previous_runtime is not None:
                previous_runtime.close()
            if self._closing:
                self._connect_results.put((generation, None, config, None))
                return
            runtime = AgentRuntime(
                config["pid"], config["cache"],
                self.output / f"pid-{config['pid']}",
                ollama=config["ollama"], mmap_path=config["mmap_path"],
                world3d_model=config["world3d_model"])
            runtime.goal(config["goal"], config["parameters"])
            if self._closing:
                runtime.close()
                self._connect_results.put((generation, None, config, None))
                return
            runtime.start()
            from adapters.atomic_file import write_json_replace
            write_json_replace(self.output / "agent_gui.json", {
                "bindings_cache": (str(config["cache"].resolve()) if config["cache"]
                                   else self._remembered_cache()),
                "goal": config["goal"],
                "mmap_path": (str(config["mmap_path"].resolve())
                              if config["mmap_path"] else "")})
            if self._closing:
                runtime.close()
                runtime = None
            self._connect_results.put((generation, runtime, config, None))
        except Exception as error:
            if runtime is not None:
                try:
                    runtime.close()
                except Exception:
                    pass
            self._connect_results.put((generation, None, config, error))

    def _finish_connections(self):
        """Apply worker results on Tk's owner thread."""
        while True:
            try:
                generation, runtime, config, error = self._connect_results.get_nowait()
            except queue.Empty:
                return
            if generation != self._connect_generation or self._closing:
                if runtime is not None:
                    threading.Thread(target=runtime.close, name="aipc-stale-runtime-close",
                                     daemon=True).start()
                continue
            self._connect_thread = None
            self._connect_started_at = None
            if error is not None:
                self.summary.set(f"Csatlakozási hiba: {type(error).__name__}: {error}")
                messagebox.showerror("AIPC csatlakozási hiba", str(error), parent=self.root)
                continue
            self.runtime = runtime
            self._model_path = config["world3d_model"]
            self.summary.set(f"PID {config['pid']} | MANUAL | runtime elindult, telemetryre vár")
            if config["auto_arm"] and config["cache"] is None:
                # Fresh PC: wait for the addon's complete binding export,
                # create a controller cache from it, then reconnect and arm.
                self.summary.set(f"PID {config['pid']} | csak export mód | binding-exportra vár…")
                self._auto_export_started = time.monotonic()
                self.root.after(1000, self._auto_export_then_arm)
                continue
            if config["auto_arm"]:
                from tools.wow_window import focus_selected_wow_window
                if not focus_selected_wow_window(config["pid"]):
                    messagebox.showerror(
                        "AIPC", f"A kiválasztott WoW PID ({config['pid']}) nem hozható "
                        "biztonságosan előtérbe; FULL_AI nem indult", parent=self.root)
                else:
                    bounded = os.environ.get("AIPC_AUTO_FULL_AI_SECONDS", "").strip()
                    if bounded:
                        # Unattended assistant-run trials: the runtime returns
                        # to MANUAL at the deadline even if nobody stops it.
                        seconds = max(5., float(bounded))
                        self._dispatch_runtime_action(
                            "időkorlátos FULL_AI próba", runtime,
                            lambda: runtime.test_step(actions=100000, seconds=seconds))
                    else:
                        self.mode("FULL_AI")

    def _remembered_cache(self) -> str:
        try:
            return str(json.loads((self.output / "agent_gui.json").read_text(
                encoding="utf-8")).get("bindings_cache") or "")
        except (OSError, ValueError):
            return ""

    AUTO_EXPORT_TIMEOUT_SECONDS = 120.

    def _auto_export_then_arm(self):
        """Export-only start: build a cache from the client's own bindings."""
        from .binding_inventory import create_controller_cache
        runtime = self.runtime
        if runtime is None or self._closing:
            return
        report = runtime.binding_inventory.report or {}
        if not report.get("complete"):
            if time.monotonic() - self._auto_export_started > self.AUTO_EXPORT_TIMEOUT_SECONDS:
                messagebox.showerror(
                    "AIPC", "A binding-export 120 s alatt sem érkezett meg teljesen; "
                    "FULL_AI nem indult (csak export mód).", parent=self.root)
                return
            self.root.after(1000, self._auto_export_then_arm)
            return
        with runtime.agent.lock:
            state = runtime.agent.world.state
            path = create_controller_cache(
                report, runtime.output, pid=runtime.pid,
                session_id=state.get("session_id"),
                character_guid=state.get("character_guid"), now=time.monotonic())
        self.cache.set(str(path))
        self.summary.set(f"PID {runtime.pid} | új controller-cache: {path.name} | újracsatlakozás")
        self.connect(auto_arm=True)

    def connect_and_arm_full_ai(self):
        """One-shot startup path; runtime keeps its normal 5-second safety gate."""
        self.connect(auto_arm=True)

    def set_goal(self):
        if not self.runtime:
            raise ValueError("Előbb csatlakozz a kiválasztott klienshez")
        parameters = json.loads(self.parameters.get() or "{}")
        if not isinstance(parameters, dict):
            raise ValueError("A célparaméterek JSON objektumot várnak")
        runtime = self.runtime
        goal = self.goal_text.get()
        self._dispatch_runtime_action(
            "cél alkalmazása", runtime, lambda: runtime.goal(goal, parameters))

    def mode(self, mode):
        if not self.runtime:
            raise ValueError("Előbb csatlakozz")
        runtime = self.runtime
        self._dispatch_runtime_action(
            f"{mode} módváltás", runtime, lambda: runtime.mode(mode))

    def test_step(self):
        if not self.runtime:
            raise ValueError("Előbb csatlakozz")
        runtime = self.runtime
        self._dispatch_runtime_action(
            "tesztlépés indítása", runtime, lambda: runtime.test_step())

    def test_run(self):
        if not self.runtime:
            raise ValueError("Előbb csatlakozz")
        runtime = self.runtime
        self._dispatch_runtime_action(
            "30 mp próba indítása", runtime,
            lambda: runtime.test_step(actions=60, seconds=30))

    def _dispatch_runtime_action(self, label, runtime, callback):
        """Run a potentially lock-waiting runtime control away from Tk."""
        if self._control_thread is not None:
            raise ValueError(f"Még folyamatban van: {self._control_label}")
        action_label = str(label)
        self._control_label = action_label
        self._control_started_at = time.monotonic()
        self.summary.set(f"Vezérlés folyamatban — {self._control_label}…")

        def worker():
            error = None
            try:
                callback()
            except Exception as caught:
                error = caught
            self._control_results.put((runtime, action_label, error))

        self._control_thread = threading.Thread(
            target=worker, name="aipc-gui-control", daemon=True)
        self._control_thread.start()

    def _finish_runtime_actions(self):
        while True:
            try:
                runtime, label, error = self._control_results.get_nowait()
            except queue.Empty:
                return
            if runtime is not self.runtime or self._closing:
                continue
            self._control_thread = None
            self._control_started_at = None
            self._control_label = None
            if error is not None:
                self.summary.set(f"Vezérlési hiba ({label}): {type(error).__name__}: {error}")
                messagebox.showerror("AIPC vezérlési hiba", str(error), parent=self.root)

    def update(self):
        try:
            self._finish_connections()
            self._finish_runtime_actions()
            if not self.runtime:
                if (self._connect_thread is not None
                        and self._connect_thread.is_alive()
                        and self._connect_started_at is not None):
                    elapsed = time.monotonic()-self._connect_started_at
                    self.summary.set(
                        f"Csatlakozás folyamatban — telemetry/runtime inicializálás… {elapsed:.1f} mp")
                return
            # ``runtime.status`` is an in-memory latest-snapshot pointer.
            # Do not serialise the full diagnostic tree in Tk's event loop:
            # live WorldModel evidence can be hundreds of KB and rewriting a
            # Text widget at 2 Hz makes the window appear frozen.
            state = self.runtime.status
            inventory = state.get("binding_inventory") or {}
            self.inventory_summary.set(
                f"Binding-export: {inventory.get('status', 'várakozás')} | "
                f"{inventory.get('pages_received', 0)}/{inventory.get('pages_expected', '?')} oldal")
            decision = state.get("decision", {})
            self.summary.set(
                f"PID {state.get('pid')} | {state.get('mode')} | {state.get('sensor')} | "
                f"{decision.get('skill', '-')} | {decision.get('reason', '')}"
                + (f" | indulás {state['arm_in']:.1f} mp" if state.get("arm_in") is not None else "")
                + (" | HIÁNYZÓ BINDING: " + ", ".join(state["binding_preflight"]["missing"])
                   if state.get("binding_preflight", {}).get("missing") else ""))
            dashboard = dashboard_projection(state, getattr(self, "_model_path", None))
            self.quest_summary.set(dashboard["quest"])
            self.control_summary.set(dashboard["control"])
            self.advisor_summary.set(dashboard["advisor"])
            if (self._control_thread is not None and self._control_thread.is_alive()
                    and self._control_started_at is not None):
                elapsed = time.monotonic()-self._control_started_at
                self.summary.set(
                    self.summary.get()
                    + f" | vezérlés: {self._control_label} ({elapsed:.1f} mp)")
            world = state.get("world") if isinstance(state.get("world"), dict) else {}
            player = world.get("player") if isinstance(world.get("player"), dict) else {}
            pending = state.get("pending") if isinstance(state.get("pending"), dict) else {}
            trigger = (state.get("mode"), decision.get("skill"), decision.get("reason"),
                       (state.get("result") or {}).get("outcome"),
                       (state.get("result") or {}).get("reason"), pending.get("action_id"),
                       player.get("target", {}).get("guid") if isinstance(player.get("target"), dict) else None,
                       player.get("quest_state_revision"), world.get("fresh"))
            now = time.monotonic()
            # The one-line summary remains responsive at 4 Hz; the bounded
            # detail text is rebuilt only for meaningful state changes or a
            # slow heartbeat, never for per-frame telemetry timestamps.
            if trigger != self._detail_trigger or now-self._detail_rendered_at >= 2.0:
                detail_json = json.dumps(self._compact_detail(state), ensure_ascii=False, indent=2)
                if detail_json != self._detail_json:
                    self.detail.delete("1.0", "end")
                    self.detail.insert("end", detail_json)
                    self._detail_json = detail_json
                self._detail_trigger = trigger
                self._detail_rendered_at = now
        except Exception as error:
            # A malformed diagnostic snapshot must not stop Tk's scheduled
            # refresh loop or interfere with the independently running agent.
            self.summary.set(f"GUI diagnosztikai frissítési hiba: {type(error).__name__}: {error}")
        finally:
            self.root.after(250, self.update)

    @staticmethod
    def _compact_detail(state):
        """Bounded GUI projection; full evidence remains in runtime/memory."""
        world = state.get("world") if isinstance(state.get("world"), dict) else {}
        inventory = (state.get("binding_inventory")
                     if isinstance(state.get("binding_inventory"), dict) else {})
        player = world.get("player") if isinstance(world.get("player"), dict) else {}
        player_keys = ("map_id", "position", "orientation", "health", "max_health", "power",
                       "max_power", "level", "class", "race", "is_mounted", "is_in_combat",
                       "is_dead", "is_ghost", "is_casting", "quest_state_revision")
        target = player.get("target") if isinstance(player.get("target"), dict) else {}
        mouseover = player.get("mouseover") if isinstance(player.get("mouseover"), dict) else {}
        target_summary = {key: target.get(key) for key in
                          ("guid", "npc_id", "name", "unit_type", "attackable", "dead", "health",
                           "max_health", "screen_position", "world_position") if key in target}
        mouseover_summary = {key: mouseover.get(key) for key in
                             ("guid", "npc_id", "name", "unit_type", "attackable", "is_dead",
                              "quest_role", "sample_time") if key in mouseover}
        quests = []
        for quest in player.get("active_quests") or []:
            if not isinstance(quest, dict):
                continue
            objectives = [{key: objective.get(key) for key in
                           ("objective_id", "description", "current", "required", "is_complete")
                           if key in objective}
                          for objective in quest.get("objectives") or [] if isinstance(objective, dict)]
            quests.append({key: quest.get(key) for key in ("quest_id", "title", "is_complete", "ready_for_turn_in")
                           if key in quest} | {"objectives": objectives[:8]})
        vision = state.get("vision_diagnostics") if isinstance(state.get("vision_diagnostics"), dict) else {}
        tracks = vision.get("tracks") if isinstance(vision.get("tracks"), list) else []
        compact_tracks = [{key: track.get(key) for key in
                           ("source", "track_id", "state", "hits", "misses", "last_seen", "lifecycle")}
                          for track in tracks[-24:] if isinstance(track, dict)]
        keys = ("mode", "goal", "decision", "result", "pending", "plan", "movement_controller",
                "map_inspection", "binding_preflight", "pid", "bindings_cache", "bindings_sha256", "sensor",
                "arm_in", "arm_waiting_for_fresh_state", "test_remaining", "timings_ms",
                "loop_rates", "runtime_scheduler", "memory_metrics", "maintenance",
                "camera_controller", "visual_approach", "vision_seek", "reasoner",
                "combat_runtime", "skill_lifecycle",
                "sensor_diagnostics", "vision", "runtime_error")
        keys = (*keys, "input_safety")
        compact = {key: state.get(key) for key in keys if key in state}
        navigation = state.get("navigation") if isinstance(state.get("navigation"), dict) else {}
        route_state = navigation.get("route") if isinstance(navigation.get("route"), dict) else {}
        compact["navigation"] = {"authority": navigation.get("authority"),
                                 "route_tail": (route_state.get("route") or [])[-8:],
                                 "blocked_destination_count": len(route_state.get("blocked_destinations") or []),
                                 "topology_feature_count": len(route_state.get("topology") or []),
                                 "movement": navigation.get("movement")}
        loop = state.get("autonomous_loop") if isinstance(state.get("autonomous_loop"), dict) else {}
        compact["autonomous_loop"] = {key: loop.get(key) for key in
                                       ("phase", "commitment", "last_replan_trigger", "replan_revision") if key in loop}
        manager = state.get("goal_manager") if isinstance(state.get("goal_manager"), dict) else {}
        compact["goal_manager"] = {key: manager.get(key) for key in
                                    ("active", "goal_status", "goal_progress", "high_level_goal_id", "persistent",
                                     "unresolved") if key in manager} | {"task_count": len(manager.get("tasks") or [])}
        compact["binding_inventory"] = {key: inventory.get(key) for key in
                                        ("status", "complete", "pages_received", "pages_expected", "path", "differences")
                                        if key in inventory}
        compact["world"] = {"session_id": world.get("session_id"), "fresh": world.get("fresh"),
                            "sensor_age": world.get("sensor_age"),
                            "player": ({key: player.get(key) for key in player_keys if key in player}
                                       | {"target": target_summary, "mouseover": mouseover_summary,
                                          "active_quests": quests[:8]}),
                            "quest_count": len(world.get("quests") or []),
                            "belief_count": len(world.get("beliefs") or {}),
                            "relation_count": len(world.get("relations") or []),
                            "event_count": len(world.get("events") or []),
                            "events": [AgentWindow._event_summary(value) for value in (world.get("events") or [])[-10:]],
                            "prediction_errors": [AgentWindow._event_summary(value) for value in (world.get("prediction_errors") or [])[-10:]],
                            "verifications": [AgentWindow._event_summary(value) for value in (world.get("verifications") or [])[-12:]],
                            "diagnostic_totals": world.get("diagnostic_totals"),
                            "observation_sources": world.get("observation_sources")}
        compact["vision_diagnostics"] = {key: value for key, value in vision.items() if key != "tracks"}
        compact["vision_diagnostics"]["tracks"] = compact_tracks
        compact["vision_diagnostics"]["track_total"] = len(tracks)
        return compact

    @staticmethod
    def _event_summary(value):
        if not isinstance(value, dict):
            return str(value)[:160]
        return {key: value.get(key) for key in
                ("event_type", "at", "sequence", "reason", "outcome", "skill", "action_id",
                 "verification_id", "prediction_id", "source", "guid") if key in value}

    def close(self):
        self._closing = True
        self._connect_generation += 1
        runtime, self.runtime = self.runtime, None
        if runtime is not None:
            # Synchronous shutdown is intentional here: releasing every held
            # key and stopping FULL_AI takes precedence over close animation.
            runtime.close()
        self.root.destroy()


def launch(output: Path, *, pid=None, bindings_cache=None, auto_full_ai=False):
    root = tk.Tk()
    window = AgentWindow(root, output, auto_full_ai=auto_full_ai)
    if pid is not None:
        window.pid.set(str(pid))
    if bindings_cache is not None:
        window.cache.set(str(bindings_cache))
    root.mainloop()
