"""InstallWizard one-click installation: the ordered stages of "Minden egyben telepites".

Split out of wizard.py (2026-10-05); unchanged.
"""
from __future__ import annotations
import shutil
import subprocess
import sys
from tkinter import messagebox
from . import checks
from .wizard_support import GUI_CONFIG, NO_WINDOW, PROJECT, RUNTIME_MODEL, STEPS


class WizardStagesMixin:
    """Methods of InstallWizard (wizard.py); moved verbatim."""

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
