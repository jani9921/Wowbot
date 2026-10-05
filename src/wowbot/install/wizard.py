"""Tkinter installation wizard for the agent (user 2026-10-02).

Every step shows its own check result and acts only on an explicit click:
Python packages, WoW Retail folder, addon, navigation data (maps / vmaps /
mmaps from the TrinityCore extractors in ``_retail_``), YOLO engine, the
unattended start (login the user types in, desktop shortcuts) and the
agent's path configuration.

User 2026-10-03: on a fresh PC one click ("Minden egyben telepítés") must
leave the agent ready to start.  No bindings cache is needed any more: the
first AUTO_START connects export-only and builds one from the addon export.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import checks

PROJECT = Path(__file__).resolve().parents[3]
GUI_CONFIG = PROJECT / "output" / "agent" / "agent_gui.json"
RUNTIME_MODEL = PROJECT / "models" / "world3d_units_3class_v10_e65.pt"
STEPS = ("Rendszer", "Python csomagok", "WoW mappa", "Addon", "Navigációs adatok",
         "YOLO modell", "Automatikus indítás", "Befejezés")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ProcessRunner:
    """Run commands one after another off the Tk thread, streaming output."""

    def __init__(self) -> None:
        self.lines: queue.SimpleQueue = queue.SimpleQueue()
        self.process: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None
        self.cancelled = False

    @property
    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, commands: list[list[str]], cwd: Path, on_done) -> None:
        self.cancelled = False
        self.thread = threading.Thread(target=self._run, args=(commands, cwd, on_done), daemon=True)
        self.thread.start()

    def _run(self, commands, cwd, on_done) -> None:
        code = 0
        for command in commands:
            if self.cancelled:
                code = None
                break
            self.lines.put(f"> {subprocess.list2cmdline(command)}")
            try:
                self.process = subprocess.Popen(
                    command, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, bufsize=0, creationflags=NO_WINDOW)
            except OSError as error:
                self.lines.put(f"Nem indítható: {error}")
                code = -1
                break
            pending = ""
            while True:
                chunk = self.process.stdout.read(4096)
                if not chunk:
                    break
                pending += chunk.decode("utf-8", errors="replace")
                parts = re.split(r"[\r\n]+", pending)
                pending = parts.pop()
                for part in parts:
                    if part.strip():
                        self.lines.put(part)
            if pending.strip():
                self.lines.put(pending)
            code = self.process.wait()
            self.lines.put(f"  -> {checks.explain_exit_code(code)}")
            if code != 0:
                break
        self.process = None
        on_done(None if self.cancelled else code)

    def cancel(self) -> None:
        self.cancelled = True
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()


class InstallWizard:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("AIPC Agent — telepítő varázsló")
        root.geometry("1000x720")
        self.runner = ProcessRunner()
        self.done_queue: queue.SimpleQueue = queue.SimpleQueue()
        self.retail = tk.StringVar(value=str(checks.detect_retail() or checks.DEFAULT_RETAIL))
        self.mmap_scope = tk.StringVar(value="selected")
        self.map_ids = tk.StringVar(value=str(checks.EXILES_REACH_MAP_ID))
        self.threads = tk.IntVar(value=max(1, (os.cpu_count() or 2) - 1))
        self.delete_buildings = tk.BooleanVar(value=False)
        login = checks.autostart_status(PROJECT)
        self.account = tk.StringVar(value=login["account"])
        self.password = tk.StringVar(value="")
        self.status: dict[str, str] = {}
        self.gpu: str | None = None
        self.torch_cuda: bool | None = None
        self.directml_ready: bool | None = None
        self.index = 0

        body = ttk.Frame(root, padding=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self.sidebar = ttk.Frame(body)
        self.sidebar.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        self.step_labels = []
        for index, title in enumerate(STEPS):
            label = ttk.Label(self.sidebar, text=title, width=24, padding=4, cursor="hand2")
            label.pack(anchor="w")
            label.bind("<Button-1>", lambda _event, i=index: self.show(i))
            self.step_labels.append(label)
        self.content = ttk.Frame(body)
        self.content.grid(row=0, column=1, sticky="nsew")
        log_frame = ttk.LabelFrame(body, text="Napló", padding=4)
        log_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        self.log = tk.Text(log_frame, height=11, wrap="none", state="disabled")
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        buttons = ttk.Frame(body)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.back_button = ttk.Button(buttons, text="< Vissza", command=lambda: self.show(self.index - 1))
        self.back_button.pack(side="left")
        self.cancel_button = ttk.Button(buttons, text="Futó folyamat leállítása", command=self.cancel)
        self.cancel_button.pack(side="left", padx=8)
        self.next_button = ttk.Button(buttons, text="Tovább >", command=lambda: self.show(self.index + 1))
        self.next_button.pack(side="right")
        self.show(0)
        self.poll()

    # ----- shared helpers -------------------------------------------------
    def write(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 3000:
            self.log.delete("1.0", "500.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def poll(self) -> None:
        for _ in range(400):
            try:
                self.write(self.runner.lines.get_nowait())
            except queue.Empty:
                break
        while True:
            try:
                callback, code = self.done_queue.get_nowait()
            except queue.Empty:
                break
            callback(code)
        self.cancel_button.state(["!disabled"] if self.runner.busy else ["disabled"])
        self.root.after(100, self.poll)

    def run(self, commands: list[list[str]], cwd: Path, title: str, after=None) -> None:
        if title.startswith("pip") or title.startswith("TensorRT telep"):
            self.torch_cuda = None   # re-check after a package change
        if self.runner.busy:
            messagebox.showinfo("Folyamatban", "Előbb várd meg vagy állítsd le a futó folyamatot.")
            return
        self.write(f"=== {title} ===")

        def finished(code):
            self.write(f"=== {title}: {'kész' if code == 0 else 'megszakítva' if code is None else 'HIBA'} ===")
            if after:
                after(code)
            self.show(self.index)

        self.runner.start(commands, cwd, lambda code: self.done_queue.put((finished, code)))

    def background(self, work, done) -> None:
        def target():
            try:
                result = work()
            except Exception as error:  # surfaced in the log, never swallowed silently
                result = error
            self.done_queue.put((done, result))
        threading.Thread(target=target, daemon=True).start()

    def cancel(self) -> None:
        if self.runner.busy and messagebox.askyesno("Leállítás", "Leállítod a futó folyamatot?"):
            self.runner.cancel()

    def set_status(self, step: str, state: str) -> None:
        self.status[step] = state
        self.refresh_marks()

    def refresh_marks(self) -> None:
        for index, title in enumerate(STEPS):
            mark = {"ok": "✔", "warn": "!", "bad": "✘"}.get(self.status.get(title, ""), "·")
            current = "► " if index == self.index else "   "
            self.step_labels[index].configure(text=f"{current}{mark} {title}")

    def show(self, index: int) -> None:
        self.index = max(0, min(len(STEPS) - 1, index))
        for child in self.content.winfo_children():
            child.destroy()
        frame = ttk.Frame(self.content)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=STEPS[self.index], font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(0, 8))
        (self.page_system, self.page_packages, self.page_wow, self.page_addon,
         self.page_navigation, self.page_models, self.page_autostart,
         self.page_finish)[self.index](frame)
        self.back_button.state(["disabled"] if self.index == 0 else ["!disabled"])
        self.next_button.state(["disabled"] if self.index == len(STEPS) - 1 else ["!disabled"])
        self.refresh_marks()

    @property
    def retail_path(self) -> Path:
        return Path(self.retail.get().strip().strip('"'))

    @staticmethod
    def line(frame, text: str, state: str | None = None) -> ttk.Label:
        prefix = {"ok": "✔ ", "warn": "! ", "bad": "✘ "}.get(state or "", "")
        label = ttk.Label(frame, text=prefix + text, wraplength=700, justify="left")
        label.pack(anchor="w", pady=1)
        return label

    # ----- pages ----------------------------------------------------------
    def page_system(self, frame) -> None:
        version = sys.version.split()[0]
        python_ok = sys.version_info[:2] >= (3, 11)
        self.line(frame, f"Python {version} ({sys.executable})", "ok" if python_ok else "bad")
        if self.gpu is None:
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                     capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
                self.gpu = out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else ""
            except (OSError, subprocess.SubprocessError):
                self.gpu = ""
        if self.gpu:
            self.line(frame, f"NVIDIA GPU: {self.gpu} (CUDA/TensorRT ellenőrzés a telepítés során)", "ok")
        else:
            vendor = self.vendor()
            self.line(frame, f"{vendor} GPU: DirectML szükséges, ezt a telepítő ellenőrzi"
                      if vendor in {"AMD", "INTEL"} else
                      "Nem található GPU — a YOLO CPU-n lassú lesz", "ok" if vendor else "warn")
        for name, path in (("projekt", PROJECT), ("WoW", self.retail_path)):
            try:
                free = shutil.disk_usage(path.anchor or path).free / 2**30
                self.line(frame, f"Szabad hely ({name} meghajtó): {free:.1f} GB",
                          "ok" if free > 20 else "warn")
            except OSError:
                pass
        self.line(frame, "Az összes mmap generálása több órát és sok GB-ot igényel; "
                         "csak a használt zónák térképei percek alatt elkészülnek.")
        self.set_status("Rendszer", "ok" if python_ok else "bad")
        box = ttk.LabelFrame(frame, text="Szűz gép: minden egyben", padding=8)
        box.pack(anchor="w", fill="x", pady=(14, 4))
        ttk.Label(box, wraplength=680, justify="left", text=(
            "Egymás után elvégzi a hiányzó lépéseket: Python csomagok (+ TensorRT, ha van NVIDIA GPU), "
            "addon, maps → vmaps → mmaps (Exile's Reach), YOLO engine erre a GPU-ra, beállítások "
            "mentése, asztali parancsikonok. A WoW mappát előbb a 'WoW mappa' lépésben ellenőrizd; "
            "az extractorokhoz rendszergazdai jog kellhet. A belépési adatokat az "
            "'Automatikus indítás' lépésben adhatod meg.")).pack(anchor="w")
        ttk.Button(box, text="Minden egyben telepítés", command=self.run_all).pack(anchor="w", pady=(6, 0))

    def page_packages(self, frame) -> None:
        status = checks.package_status()
        table = ttk.Frame(frame)
        table.pack(anchor="w", fill="x")
        for row, (module, dist, purpose, version) in enumerate(status["required"] + status["optional"]):
            optional = row >= len(status["required"])
            state = "ok" if version else ("warn" if optional else "bad")
            ttk.Label(table, text={"ok": "✔", "warn": "!", "bad": "✘"}[state]).grid(row=row, column=0, sticky="w")
            ttk.Label(table, text=dist, width=16).grid(row=row, column=1, sticky="w")
            ttk.Label(table, text=version or "nincs telepítve", width=22).grid(row=row, column=2, sticky="w")
            ttk.Label(table, text=purpose).grid(row=row, column=3, sticky="w")
        missing = [dist for _m, dist, _p, version in status["required"] if version is None]
        torch_installed = next(version for _m, dist, _p, version in status["required"] if dist == "torch")
        if torch_installed and self.torch_cuda is None:
            self.line(frame, "Torch CUDA ellenőrzése…")

            def cuda_done(result):
                self.torch_cuda = result if isinstance(result, bool) else False
                if self.index == STEPS.index("Python csomagok") and not self.runner.busy:
                    self.show(self.index)

            self.background(lambda: subprocess.run(
                [sys.executable, "-c", "import torch;print(torch.cuda.is_available())"],
                capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW).stdout.strip() == "True",
                cuda_done)
        elif torch_installed:
            self.line(frame, "Torch látja a GPU-t (CUDA)" if self.torch_cuda else
                      "Torch nem látja a GPU-t (CPU-s torch vagy nincs GPU)",
                      "ok" if self.torch_cuda else "warn")
        ok = not missing and (self.torch_cuda or not self.gpu)
        self.set_status("Python csomagok", "ok" if ok else ("bad" if missing else "warn"))
        commands = checks.pip_commands(sys.executable, status, gpu=bool(self.gpu), torch_cuda=self.torch_cuda)
        if commands:
            ttk.Button(frame, text="Hiányzó csomagok telepítése",
                       command=lambda: self.run(commands, PROJECT, "pip telepítés")).pack(anchor="w", pady=8)
        else:
            self.line(frame, "Minden szükséges csomag telepítve van.", "ok")
        if not self.gpu and self.vendor() in {"AMD", "INTEL"}:
            dml = checks.directml_command(sys.executable, status)
            if dml:
                ttk.Button(frame, text=f"DirectML telepítése ({self.vendor()} GPU-hoz)",
                           command=lambda: self.run([dml], PROJECT, "DirectML telepítés")).pack(anchor="w", pady=(0, 6))
            else:
                self.line(frame, "DirectML (onnxruntime-directml) telepítve: a YOLO a GPU-n fut.", "ok")
        if self.gpu:
            ttk.Button(frame, text="TensorRT telepítése (NVIDIA)",
                       command=lambda: self.run([[sys.executable, "-m", "pip", "install", "tensorrt-cu12"]],
                                                PROJECT, "TensorRT telepítés")).pack(anchor="w")

    def page_wow(self, frame) -> None:
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="_retail_ mappa:").pack(side="left")
        ttk.Entry(row, textvariable=self.retail, width=70).pack(side="left", padx=6, fill="x", expand=True)
        ttk.Button(row, text="Tallózás", command=self.browse_retail).pack(side="left")
        ttk.Button(row, text="Ellenőrzés", command=lambda: self.show(self.index)).pack(side="left", padx=4)
        result = checks.validate_retail(self.retail_path)
        self.line(frame, f"Wow.exe {'megvan' if result['wow_exe'] else 'nem található'}",
                  "ok" if result["wow_exe"] else "bad")
        version = result["client_version"] or "ismeretlen"
        self.line(frame, f"Kliens verzió: {version} (elvárt: 12.1.x)", "ok" if result["version_ok"] else "warn")
        for name, present in result["extractors"].items():
            self.line(frame, f"{name} {'megvan' if present else 'HIÁNYZIK'}", "ok" if present else "bad")
        self.line(frame, f"{result['dll_count']} DLL a mappában (az extractorok ezeket használják)")
        if not result["writable"] and result["exists"]:
            self.line(frame, "A mappa nem írható: az extractorokhoz rendszergazdai jog kell.", "bad")
            ttk.Button(frame, text="Varázsló újraindítása rendszergazdaként",
                       command=self.relaunch_as_admin).pack(anchor="w", pady=6)
        state = "ok" if result["ok"] and result["writable"] else "bad" if not result["ok"] else "warn"
        self.set_status("WoW mappa", state)

    def page_addon(self, frame) -> None:
        status = checks.addon_status(PROJECT, self.retail_path)
        self.line(frame, f"Projekt addon verzió: {status['project_version']}")
        installed = status["installed_version"]
        self.line(frame, f"Telepített verzió: {installed or 'nincs telepítve'}",
                  "ok" if status["up_to_date"] else "warn")
        self.line(frame, f"Cél: {status['target']}")

        def install():
            try:
                copied = checks.install_addon(PROJECT, self.retail_path)
                self.write(f"Addon telepítve ({', '.join(copied)}) -> {status['target']}")
                messagebox.showinfo("Addon", "Addon telepítve. A játékban írd be: /reload")
            except OSError as error:
                messagebox.showerror("Addon", f"Nem sikerült: {error}")
            self.show(self.index)

        ttk.Button(frame, text="Addon telepítése / frissítése", command=install).pack(anchor="w", pady=8)
        self.set_status("Addon", "ok" if status["up_to_date"] else "warn")

    def page_navigation(self, frame) -> None:
        retail = self.retail_path
        info = self.line(frame, "Navigációs adatok ellenőrzése…")
        steps = ttk.Frame(frame)
        steps.pack(anchor="w", fill="x", pady=6)

        def render(status):
            if isinstance(status, Exception):
                self.set_status("Navigációs adatok", "bad")
                if info.winfo_exists():
                    info.configure(text=f"✘ Ellenőrzési hiba: {status}")
                return
            focus = status["focus"][checks.EXILES_REACH_MAP_ID]
            have_maps, have_vmaps = focus["maps"], focus["vmaps"]
            ready = focus["mmaps"]
            # Recorded even when the user already moved to another page.
            self.set_status("Navigációs adatok", "ok" if ready and have_maps and have_vmaps else "bad")
            if not info.winfo_exists():
                return
            info.configure(text=(
                f"maps: {status['maps_count']} térkép | vmaps: {status['vmaps_count']} térkép | "
                f"mmaps: {status['mmaps_count']} térkép ({retail / 'mmaps'})\n"
                f"Exile's Reach (2175): maps {'✔' if focus['maps'] else '✘'}  "
                f"vmaps {'✔' if focus['vmaps'] else '✘'}  mmaps {'✔' if focus['mmaps'] else '✘'}"
                + (f"\nKész mmap-ek: {', '.join(str(i) for i in status['mmap_ids'][:20])}"
                   + (" …" if len(status["mmap_ids"]) > 20 else "") if status["mmap_ids"] else "")))
            ttk.Button(steps, text="1. maps kinyerése (mapextractor)",
                       command=lambda: self.run(checks.extraction_commands("maps", retail), retail,
                                                "maps kinyerése")).grid(row=0, column=0, sticky="w", pady=2)
            ttk.Label(steps, text="✔ megvan" if have_maps else "szükséges").grid(row=0, column=1, sticky="w", padx=8)
            vm = ttk.Button(steps, text="2. vmaps kinyerése (vmap4extractor + assembler)",
                            command=self.extract_vmaps)
            vm.grid(row=1, column=0, sticky="w", pady=2)
            vm.state(["!disabled"] if have_maps else ["disabled"])
            ttk.Label(steps, text="✔ megvan" if have_vmaps else "a maps után").grid(row=1, column=1, sticky="w", padx=8)
            ttk.Checkbutton(steps, text="Az ideiglenes Buildings mappa törlése a vmaps után"
                            + (" (most is ott van)" if status["buildings_present"] else ""),
                            variable=self.delete_buildings).grid(row=2, column=0, columnspan=2, sticky="w")
            options = ttk.LabelFrame(frame, text="3. mmaps generálása (mmaps_generator)", padding=6)
            options.pack(anchor="w", fill="x", pady=6)
            ttk.Radiobutton(options, text="Csak ezek a térképek (gyors):", value="selected",
                            variable=self.mmap_scope).grid(row=0, column=0, sticky="w")
            ttk.Entry(options, textvariable=self.map_ids, width=30).grid(row=0, column=1, sticky="w")
            ttk.Label(options, text="pl. 2175 = Exile's Reach; vesszővel több is").grid(row=0, column=2, sticky="w", padx=6)
            ttk.Radiobutton(options, text="Az összes térkép (több óra, sok GB)", value="all",
                            variable=self.mmap_scope).grid(row=1, column=0, columnspan=3, sticky="w")
            ttk.Label(options, text="Szálak:").grid(row=2, column=0, sticky="e")
            ttk.Spinbox(options, from_=1, to=max(1, os.cpu_count() or 1), textvariable=self.threads,
                        width=5).grid(row=2, column=1, sticky="w")
            mm = ttk.Button(options, text="mmaps generálása", command=self.generate_mmaps)
            mm.grid(row=3, column=0, sticky="w", pady=4)
            mm.state(["!disabled"] if have_maps and have_vmaps else ["disabled"])

        self.background(lambda: checks.navigation_status(retail), render)

    def extract_vmaps(self) -> None:
        retail = self.retail_path

        def after(code):
            if code == 0 and self.delete_buildings.get() and (retail / "Buildings").is_dir():
                if messagebox.askyesno("Buildings", "Törlöd az ideiglenes Buildings mappát? (Véglegesen törlődik.)"):
                    shutil.rmtree(retail / "Buildings", ignore_errors=True)
                    self.write("Buildings mappa törölve.")

        self.run(checks.extraction_commands("vmaps", retail), retail, "vmaps kinyerése", after)

    def generate_mmaps(self) -> None:
        retail = self.retail_path
        if self.mmap_scope.get() == "all":
            if not messagebox.askyesno("Összes mmap", "Az összes térkép generálása több órát vesz igénybe. Indítod?"):
                return
            map_ids = None
        else:
            try:
                map_ids = checks.parse_map_ids(self.map_ids.get())
            except ValueError as error:
                messagebox.showerror("Térképek", str(error))
                return
        commands = checks.extraction_commands("mmaps", retail, map_ids=map_ids, threads=self.threads.get())
        self.run(commands, retail, "mmaps generálása")

    def page_models(self, frame) -> None:
        vendor = "NVIDIA" if self.gpu else self.vendor()
        if vendor in {"AMD", "INTEL"} and self.directml_ready is None:
            self.line(frame, "DirectML provider ellenőrzése…")

            def checked(value):
                self.directml_ready = value is True
                if self.index == STEPS.index("YOLO modell") and not self.runner.busy:
                    self.show(self.index)

            self.background(checks.probe_directml, checked)
        status = checks.runtime_model_status(PROJECT, vendor,
                                             torch_cuda=bool(self.torch_cuda),
                                             directml=bool(self.directml_ready))
        engine = RUNTIME_MODEL.with_suffix(".engine")
        self.line(frame, f"Futásidejű modell: {RUNTIME_MODEL.name} {'megvan' if RUNTIME_MODEL.is_file() else 'HIÁNYZIK'}",
                  "ok" if RUNTIME_MODEL.is_file() else "bad")
        self.line(frame, f"Várható YOLO backend: {status['backend']} ({status['model_name'] or 'nincs modell'})",
                  "ok" if status["accelerated"] else "warn")
        if vendor == "NVIDIA":
            self.line(frame, f"TensorRT engine: {'megvan' if engine.is_file() else 'nincs'}; "
                             "másik GPU-ról hozott engine-t újra kell építeni.",
                      "ok" if engine.is_file() else "warn")
        elif vendor in {"AMD", "INTEL"}:
            self.line(frame, f"ONNX modell: {'megvan' if status['onnx'] else 'HIÁNYZIK'}; "
                             "DirectML provider szükséges.", "ok" if status["onnx"] else "bad")

        def build():
            if engine.is_file() and not messagebox.askyesno(
                    "Engine", "Már van engine. Újraépíted erre a GPU-ra (felülírja)?"):
                return
            code = ("from ultralytics import YOLO; YOLO(r'%s').export(format='engine', imgsz=640, half=True, "
                    "batch=1, simplify=True, dynamic=False, device=0)" % RUNTIME_MODEL)
            self.run([[sys.executable, "-c", code]], PROJECT, "TensorRT engine építése")

        button = ttk.Button(frame, text="TensorRT engine építése ehhez a GPU-hoz", command=build)
        button.pack(anchor="w", pady=8)
        button.state(["!disabled"] if RUNTIME_MODEL.is_file() and vendor == "NVIDIA" else ["disabled"])
        self.set_status("YOLO modell", "ok" if RUNTIME_MODEL.is_file() else "bad")

    def page_autostart(self, frame) -> None:
        login = checks.autostart_status(PROJECT)
        ready = bool(login["account"] and login["password_saved"])
        self.line(frame, "Az AUTO_START elindítja a WoW-ot, belép, kiválasztja a karaktert és "
                         "elindítja az agentet. Első indításkor az addon billentyű-exportjából "
                         "magától készít bindings-cache-t.")
        self.line(frame, f"Fiók: {login['account'] or 'nincs megadva'}",
                  "ok" if login["account"] else "warn")
        self.line(frame, "Jelszó elmentve (config\\wow_password.txt)" if login["password_saved"]
                  else "Nincs elmentett jelszó: az AUTO_START nem tud belépni", "ok" if login["password_saved"] else "warn")
        form = ttk.Frame(frame)
        form.pack(anchor="w", pady=8)
        ttk.Label(form, text="Fiók (e-mail / név):").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.account, width=40).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(form, text="Jelszó:").grid(row=1, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.password, width=40, show="•").grid(row=1, column=1, sticky="w", padx=6)
        ttk.Label(frame, wraplength=680, justify="left", text=(
            "A jelszó csak ezen a gépen, titkosítatlanul kerül a config\\wow_password.txt fájlba. "
            "Üresen hagyva a meglévő fájl nem változik.")).pack(anchor="w")

        def save():
            written = checks.write_autostart_login(PROJECT, self.account.get(), self.password.get())
            self.password.set("")
            self.write("Mentve: " + ", ".join(path.name for path in written) if written else "Nincs mit menteni.")
            self.show(self.index)

        ttk.Button(frame, text="Belépési adatok mentése", command=save).pack(anchor="w", pady=(6, 2))
        ttk.Button(frame, text="Asztali parancsikonok létrehozása",
                   command=lambda: self.run([checks.shortcut_command(PROJECT)], PROJECT,
                                            "parancsikonok")).pack(anchor="w", pady=2)
        self.set_status("Automatikus indítás", "ok" if ready else "warn")

    def page_finish(self, frame) -> None:
        retail = self.retail_path
        mmaps = retail / "mmaps"
        has_mmaps = not checks.required_navigation_steps(checks.navigation_status(retail))
        for title in STEPS[:-1]:
            state = self.status.get(title)
            self.line(frame, f"{title}: {'rendben' if state == 'ok' else 'figyelmeztetés' if state == 'warn' else 'hiányos vagy nem ellenőrzött' if state else 'nem ellenőrzött'}",
                      state or "warn")
        self.line(frame, "Bindings-cache nem kell: az első AUTO_START csak-export módban csatlakozik, "
                         "az addon billentyű-exportjából készít egyet, majd újracsatlakozik.")
        vendor = "NVIDIA" if self._has_gpu() else self.vendor()
        probe = checks.probe_torch_cuda if vendor == "NVIDIA" else checks.probe_directml
        result_attr = "torch_cuda" if vendor == "NVIDIA" else "directml_ready"
        if vendor in {"NVIDIA", "AMD", "INTEL"} and getattr(self, result_attr) is None:
            self.line(frame, f"{vendor} GPU-provider ellenőrzése folyamatban…", "warn")

            def checked(ready):
                setattr(self, result_attr, ready is True)
                if self.index == STEPS.index("Befejezés"):
                    self.show(self.index)

            self.background(probe, checked)
        else:
            model = checks.runtime_model_status(
                PROJECT, vendor, torch_cuda=bool(self.torch_cuda),
                directml=bool(self.directml_ready))
            self.line(frame, "Agent logika: CPU (WorldModel, tervezés, vezérlés).")
            self.line(frame, f"YOLO detektor várható futása: {model['backend']} | "
                             f"modell: {model['model_name'] or 'HIÁNYZIK'}",
                      "ok" if model["accelerated"] else "warn")
            self.line(frame, "A tényleges GPU-futtatást az agent indítási naplója igazolja; "
                             "egy meglévő TensorRT engine kompatibilitását a fájl megléte önmagában nem bizonyítja.")
        issues = checks.installation_issues(
            PROJECT, retail, vendor, torch_cuda=bool(self.torch_cuda),
            directml=bool(self.directml_ready))
        for issue in issues:
            self.line(frame, "Még nem kész: " + issue, "bad")
        for warning in checks.installation_warnings(
                PROJECT, vendor, torch_cuda=bool(self.torch_cuda),
                directml=bool(self.directml_ready)):
            self.line(frame, "Figyelmeztetés: " + warning, "warn")
        llm = checks.ollama_status(PROJECT, timeout=.5)
        llm_ready = llm["running"] and llm["model_present"]
        self.line(frame, "Helyi MI (opcionális, bonyolult questek szövegéhez): "
                         + ("kész" if llm_ready else
                            f"Ollama {'fut' if llm['running'] else 'telepítve, nem fut' if llm['installed'] else 'nincs telepítve'}"
                            f", modell ({llm['model'] or '—'}) {'megvan' if llm['model_present'] else 'nincs letöltve'}"),
                  "ok" if llm_ready else "warn")
        if not llm_ready:
            ttk.Button(frame, text="Helyi MI telepítése / modell letöltése (Ollama)",
                       command=lambda: self._stage_ollama(lambda _ok: self.show(self.index))
                       ).pack(anchor="w", pady=(4, 2))

        def save():
            if not has_mmaps and not messagebox.askyesno(
                    "mmaps", f"A {mmaps} mappában még nincs mmap. Így is elmented?"):
                return
            env = checks.write_local_env(PROJECT, retail)
            checks.update_gui_config(GUI_CONFIG, mmaps)
            self.write(f"Beállítás mentve: {env} és {GUI_CONFIG} (mmap: {mmaps})")
            messagebox.showinfo("Mentve", "Az agent mostantól a _retail_ mappából olvassa a navigációs adatokat.")

        ttk.Button(frame, text="Beállítások mentése (navigáció a _retail_ mappából)",
                   command=save).pack(anchor="w", pady=(10, 4))
        ttk.Button(frame, text="Indítás most: WoW + belépés + agent (AUTO_START.bat)",
                   command=self.start_autostart).pack(anchor="w", pady=2)
        ttk.Button(frame, text="Agent indítása kézzel (START_AGENT.bat)", command=self.start_agent).pack(anchor="w")
        self.set_status("Befejezés", "bad" if issues else "ok")

    # ----- actions --------------------------------------------------------
    def browse_retail(self) -> None:
        path = filedialog.askdirectory(title="WoW _retail_ mappa kiválasztása")
        if path:
            self.retail.set(path)
            self.show(self.index)

    def relaunch_as_admin(self) -> None:
        script = PROJECT / "tools" / "install_wizard.py"
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}"', str(PROJECT), 1)
        self.root.destroy()

    def start_autostart(self) -> None:
        if not checks.autostart_status(PROJECT)["password_saved"]:
            messagebox.showwarning("AUTO_START", "Előbb mentsd el a belépési adatokat "
                                   "az 'Automatikus indítás' lépésben.")
            return
        # User rule: a live trial lasts at most 3-5 minutes, never 20.
        if not messagebox.askyesno("AUTO_START", "Elindítod a WoW-ot és az agentet (5 perces próba)?"):
            return
        subprocess.Popen(["cmd", "/c", "start", "", str(PROJECT / "AUTO_START.bat"),
                          "--trial-seconds", "300"], cwd=str(PROJECT))

    # ----- one-click installation ----------------------------------------------
    def run_all(self) -> None:
        """Run every missing step in order; stop at the first failure."""
        if self.runner.busy:
            messagebox.showinfo("Folyamatban", "Előbb várd meg a futó folyamatot.")
            return
        if sys.version_info[:2] < (3, 11):
            messagebox.showerror("Python", "Legalább Python 3.11 szükséges; a telepítés nem indulhat ezzel az interpreterrel.")
            self.show(STEPS.index("Rendszer"))
            return
        retail = self.retail_path
        validation = checks.validate_retail(retail)
        if not validation["ok"]:
            messagebox.showerror("WoW mappa", "A _retail_ mappa nem érvényes; ellenőrizd a 'WoW mappa' lépésben.")
            self.show(STEPS.index("WoW mappa"))
            return
        if not validation["writable"]:
            if messagebox.askyesno("Rendszergazda", "Az extractorokhoz írni kell a _retail_ mappába. "
                                   "Újraindítod a varázslót rendszergazdaként?"):
                self.relaunch_as_admin()
            return
        stages = [self._stage_packages, self._stage_tensorrt, self._stage_directml,
                  self._stage_addon,
                  self._stage_maps, self._stage_vmaps, self._stage_mmaps,
                  self._stage_engine, self._stage_verify, self._stage_save,
                  self._stage_shortcuts, self._stage_ollama]
        self.write("=== Minden egyben telepítés ===")

        def advance(index: int = 0) -> None:
            if index >= len(stages):
                self.write("=== Minden egyben telepítés: kész ===")
                self.show(STEPS.index("Befejezés"))
                vendor = "NVIDIA" if self._has_gpu() else self.vendor()
                model = checks.runtime_model_status(
                    PROJECT, vendor, torch_cuda=bool(self.torch_cuda),
                    directml=bool(self.directml_ready))
                warnings = checks.installation_warnings(
                    PROJECT, vendor, torch_cuda=bool(self.torch_cuda),
                    directml=bool(self.directml_ready))
                messagebox.showinfo(
                    "Kész", "A telepítés kész.\n"
                    "Agent logika: CPU\n"
                    f"YOLO detektor várható futása: {model['backend']}\n"
                    f"Modell: {model['model_name'] or 'HIÁNYZIK'}\n"
                    + "".join(f"Figyelmeztetés: {warning}\n" for warning in warnings) +
                    "A tényleges backend az agent indítási naplójában ellenőrizhető. "
                    "Az AUTO_START-hoz add meg a belépési adatokat az Automatikus indítás lapon.")
                return
            stages[index](lambda ok=True: advance(index + 1) if ok else self.write(
                "=== Minden egyben telepítés megállt; nézd meg a naplót ==="))

        advance()

    def _run_stage(self, commands, cwd, title, done) -> None:
        if not commands:
            done(True)
            return
        self.run(commands, cwd, title, after=lambda code: done(code == 0))

    def _stage_packages(self, done) -> None:
        status = checks.package_status()
        nvidia = self._has_gpu()
        torch_installed = any(dist == "torch" and version for _m, dist, _p, version
                              in status["required"])

        def install(cuda_available):
            self.torch_cuda = (cuda_available is True) if nvidia else False
            commands = checks.pip_commands(
                sys.executable, status, gpu=nvidia, torch_cuda=self.torch_cuda)

            def installed(ok):
                if not ok:
                    done(False)
                elif nvidia:
                    self.background(checks.probe_torch_cuda, verified)
                else:
                    done(True)

            def verified(value):
                self.torch_cuda = value is True
                if not self.torch_cuda:
                    # Not fatal: the agent still runs (CPU YOLO); addon and
                    # navigation must not be skipped because of it.
                    self.write("FIGYELEM: CUDA Torch nem használható (illesztőprogram?); "
                               "a YOLO CPU-n fog futni. A telepítés folytatódik.")
                done(True)

            self._run_stage(commands, PROJECT, "pip telepítés", installed)

        if nvidia and torch_installed:
            self.background(checks.probe_torch_cuda, install)
        else:
            install(False)

    def vendor(self) -> str:
        if getattr(self, "_vendor", None) is None:
            self._vendor = checks.gpu_vendor()
        return self._vendor

    def _has_gpu(self) -> bool:
        if self.gpu is None:
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                                     capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
                self.gpu = out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else ""
            except (OSError, subprocess.SubprocessError):
                self.gpu = ""
        return bool(self.gpu)

    def _stage_tensorrt(self, done) -> None:
        if not self._has_gpu():
            done(True)
            return
        def optional(value):
            if value is not True:
                self.write("FIGYELEM: TensorRT nem érhető el; a YOLO PyTorch CUDA-val fut. "
                           "A telepítés folytatódik.")
            done(True)

        def checked(ready):
            if ready is True:
                done(True)
            else:
                self._run_stage(
                    [[sys.executable, "-m", "pip", "install", "--upgrade", "tensorrt-cu12"]],
                    PROJECT, "TensorRT telepítés",
                    lambda ok: self.background(checks.probe_tensorrt, optional) if ok else optional(False))
        self.background(checks.probe_tensorrt, checked)

    def _stage_directml(self, done) -> None:
        if self._has_gpu() or self.vendor() not in {"AMD", "INTEL"}:
            done(True)
            return
        if not RUNTIME_MODEL.with_suffix(".onnx").is_file():
            self.write("FIGYELEM: DirectML-hez hiányzik a csomagolt ONNX modell; a YOLO CPU-n fut.")
            done(True)
            return

        def checked(ready):
            if ready is True:
                self.directml_ready = True
                done(True)
                return
            command = checks.directml_command(sys.executable, checks.package_status())
            # A registered distribution is not proof that the DML provider
            # loads. Reinstall it when the provider probe failed.
            command = command or [sys.executable, "-m", "pip", "install", "--upgrade",
                                  "--force-reinstall", "onnxruntime-directml"]
            self._run_stage([command], PROJECT, "DirectML telepítés",
                            lambda ok: self.background(checks.probe_directml, verified)
                            if ok else verified(False))

        def verified(ready):
            self.directml_ready = ready is True
            if not self.directml_ready:
                self.write("FIGYELEM: DirectML provider nem érhető el; a YOLO CPU-n fut. "
                           "A telepítés folytatódik.")
            done(True)

        self.background(checks.probe_directml, checked)

    def _stage_addon(self, done) -> None:
        try:
            copied = checks.install_addon(PROJECT, self.retail_path)
            self.write(f"Addon telepítve ({', '.join(copied)})")
            done(True)
        except OSError as error:
            self.write(f"Addon telepítési hiba: {error}")
            done(False)

    def _navigation(self) -> dict:
        return checks.navigation_status(self.retail_path)

    def _stage_maps(self, done) -> None:
        if self._navigation()["focus"][checks.EXILES_REACH_MAP_ID]["maps"]:
            done(True)
            return
        if not (self.retail_path / "mapextractor.exe").is_file():
            self.write("Hiányzik a mapextractor.exe; tedd a Retail mappába az extractorokat.")
            done(False)
            return
        self._run_stage(checks.extraction_commands("maps", self.retail_path), self.retail_path,
                        "maps kinyerése", done)

    def _stage_vmaps(self, done) -> None:
        if self._navigation()["focus"][checks.EXILES_REACH_MAP_ID]["vmaps"]:
            done(True)
            return
        if not all((self.retail_path / name).is_file()
                   for name in ("vmap4extractor.exe", "vmap4assembler.exe")):
            self.write("Hiányzik a vmap4extractor.exe vagy vmap4assembler.exe.")
            done(False)
            return
        self._run_stage(checks.extraction_commands("vmaps", self.retail_path), self.retail_path,
                        "vmaps kinyerése", done)

    def _stage_mmaps(self, done) -> None:
        if self._navigation()["focus"][checks.EXILES_REACH_MAP_ID]["mmaps"]:
            done(True)
            return
        if not (self.retail_path / "mmaps_generator.exe").is_file():
            self.write("Hiányzik a mmaps_generator.exe; mmap nem készíthető.")
            done(False)
            return
        commands = checks.extraction_commands("mmaps", self.retail_path,
                                              map_ids=[checks.EXILES_REACH_MAP_ID],
                                              threads=self.threads.get())
        self._run_stage(commands, self.retail_path, "mmaps generálása (Exile's Reach)", done)

    def _stage_engine(self, done) -> None:
        engine = RUNTIME_MODEL.with_suffix(".engine")
        if not self._has_gpu():
            done(True)
            return
        if not RUNTIME_MODEL.is_file() or not self.torch_cuda:
            self.write("FIGYELEM: a CUDA modell vagy Torch hiányzik; TensorRT engine nem épül.")
            done(True)
            return
        if engine.is_file():
            done(True)
            return
        code = ("from ultralytics import YOLO; YOLO(r'%s').export(format='engine', imgsz=640, half=True, "
                "batch=1, simplify=True, dynamic=False, device=0)" % RUNTIME_MODEL)

        def built(ok):
            if not (ok and engine.is_file()):
                self.write("FIGYELEM: a TensorRT engine nem épült meg; a YOLO PyTorch CUDA-val fut.")
            done(True)

        self._run_stage([[sys.executable, "-c", code]], PROJECT, "TensorRT engine építése", built)

    def _stage_verify(self, done) -> None:
        vendor = "NVIDIA" if self._has_gpu() else self.vendor()
        issues = checks.installation_issues(
            PROJECT, self.retail_path, vendor, torch_cuda=bool(self.torch_cuda),
            directml=bool(self.directml_ready))
        for issue in issues:
            self.write("Nincs kész: " + issue)
        for warning in checks.installation_warnings(
                PROJECT, vendor, torch_cuda=bool(self.torch_cuda),
                directml=bool(self.directml_ready)):
            self.write("Figyelmeztetés: " + warning)
        done(not issues)

    def _stage_save(self, done) -> None:
        retail = self.retail_path
        env = checks.write_local_env(PROJECT, retail)
        checks.update_gui_config(GUI_CONFIG, retail / "mmaps")
        self.write(f"Beállítás mentve: {env} és {GUI_CONFIG}")
        done(True)

    def _stage_shortcuts(self, done) -> None:
        self._run_stage([checks.shortcut_command(PROJECT)], PROJECT, "parancsikonok",
                        lambda ok: done(bool(ok)))

    def _stage_ollama(self, done, *, ask: bool = True) -> None:
        """Optional local LLM (user 2026-10-05: "ollamát is telepít meg AI-t?").

        Installs Ollama with winget, starts its server and pulls the model
        from config/ai_decision.json.  Never fatal: the agent runs without
        it (the quest-text interpreter just stays idle).
        """
        status = checks.ollama_status(PROJECT)
        model = status["model"]
        if not model or (status["running"] and status["model_present"]):
            done(True)
            return
        if ask and not messagebox.askyesno(
                "Helyi MI (opcionális)",
                "Telepítsem a helyi MI-t a bonyolultabb questek szövegéhez?\n"
                f"- Ollama {'(már telepítve)' if status['installed'] else '(winget, kb. 1 GB)'}\n"
                f"- modell: {model} (kb. 2,5 GB letöltés)\n"
                "A telepítéssel elfogadod az Ollama licencét. Nélküle is fut az agent."):
            self.write("Helyi MI kihagyva (nem kötelező).")
            done(True)
            return

        def skipped(reason: str) -> None:
            self.write(f"FIGYELEM: helyi MI nincs kész ({reason}); az agent nélküle fut.")
            done(True)

        def pull() -> None:
            executable = checks.ollama_executable()
            if executable is None:
                skipped("az ollama.exe nem található")
                return
            self._run_stage([[str(executable), "pull", model]], PROJECT, f"MI modell letöltése ({model})",
                            lambda ok: done(True) if ok else skipped("a modell letöltése nem sikerült"))

        def serving(ready) -> None:
            if ready is not True:
                skipped("az Ollama szerver nem indult el")
            elif checks.ollama_status(PROJECT)["model_present"]:
                done(True)
            else:
                pull()

        def start_server() -> None:
            executable = checks.ollama_executable()
            if executable is None:
                skipped("az ollama.exe nem található")
                return
            if not checks.ollama_status(PROJECT)["running"]:
                subprocess.Popen([str(executable), "serve"], cwd=str(PROJECT), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0))

            def wait_for_server() -> bool:
                import time
                for _ in range(30):
                    if checks.ollama_status(PROJECT)["running"]:
                        return True
                    time.sleep(1.)
                return False

            self.background(wait_for_server, serving)

        if status["installed"]:
            start_server()
        elif shutil.which("winget"):
            self._run_stage([["winget", "install", "-e", "--id", "Ollama.Ollama",
                              "--accept-source-agreements", "--accept-package-agreements"]],
                            PROJECT, "Ollama telepítése (winget)",
                            lambda ok: start_server() if ok else skipped("a winget telepítés nem sikerült"))
        else:
            skipped("nincs winget; telepítsd kézzel: https://ollama.com")

    def start_agent(self) -> None:
        if not messagebox.askyesno("Agent", "Elindítod az agentet (MANUAL módban indul)?"):
            return
        subprocess.Popen(["cmd", "/c", "start", "", str(PROJECT / "START_AGENT.bat")], cwd=str(PROJECT))


def main() -> int:
    root = tk.Tk()
    InstallWizard(root)
    root.mainloop()
    return 0
