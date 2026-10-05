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

import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import checks
# Moved to wizard_support.py 2026-10-05; re-exported for existing callers.
from .wizard_support import (  # noqa: F401
    GUI_CONFIG, NO_WINDOW, PROJECT, ProcessRunner, RUNTIME_MODEL, STEPS,
)
from .wizard_pages import WizardPagesMixin
from .wizard_stages import WizardStagesMixin


class InstallWizard(WizardStagesMixin, WizardPagesMixin):
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


def main() -> int:
    root = tk.Tk()
    InstallWizard(root)
    root.mainloop()
    return 0
