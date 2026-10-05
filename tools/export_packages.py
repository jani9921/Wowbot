"""Build the move-to-another-PC zip and/or a clean GitHub-ready source tree.

    python tools/export_packages.py --migration      # export/AIPC_migration_<date>.zip
    python tools/export_packages.py --github         # export/github/wow-ai-agent/

User 2026-10-04.  Neither package ever contains the login files
(config/wow_password.txt, config/wow_account.txt): copy those by hand.

* migration: everything needed to continue on another PC, including the
  learned profile memory (output/agent/profiles), the current TDB spawn
  catalog and all .pt/.onnx models.  No per-run logs/captures, no NVIDIA-only
  TensorRT .engine files (the install wizard rebuilds them for the new GPU),
  no training datasets/runs.
* github: source, tests, tools, addon, docs, the install wizard and only the
  runtime YOLO model; no personal data (profiles, logs, captures), no
  third-party databases or nested git checkouts.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import fnmatch
import os
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT.parent / "export"

NEVER = {"config/wow_password.txt", "config/wow_account.txt",
         # per-machine paths written by the install wizard
         "config/local_env.bat"}
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", ".runtime-data", "datasets", "runs", ".vscode"}
SKIP_FILES = ["*.pyc", "*.engine", "runs_*.log", "*.tmp"]

MIGRATION_EXTRA_SKIP = ["data/tdb_spawn_catalog.*.sqlite3"]
GITHUB_SKIP = ["data/*.sqlite3", "weights/*", "native/recastnavigation/*", "native/recastnavigation"]
GITHUB_MODELS = {"world3d_units_3class_v10_e65.pt", "world3d_units_3class_v10_e65.onnx",
                 "world3d_units_3class_v10_e65_512.pt", "world3d_units_3class_v10_e65_512.onnx"}


def _match(relative: str, patterns) -> bool:
    return any(fnmatch.fnmatch(relative, pattern) for pattern in patterns)


def iter_files(mode: str):
    """Yield (absolute path, archive-relative posix path) for one package."""
    for directory, dirs, files in os.walk(ROOT):
        current = Path(directory)
        relative_dir = current.relative_to(ROOT).as_posix()
        relative_dir = "" if relative_dir == "." else relative_dir
        keep_dirs = []
        for name in dirs:
            rel = f"{relative_dir}/{name}" if relative_dir else name
            if name in SKIP_DIRS:
                continue
            if rel == "output":
                if mode == "migration":
                    keep_dirs.append(name)       # only output/agent/profiles below
                continue
            if rel.startswith("output/") and not (
                    "output/agent/profiles".startswith(rel) or rel.startswith("output/agent/profiles")):
                continue
            if mode == "github" and _match(rel, GITHUB_SKIP):
                continue
            keep_dirs.append(name)
        dirs[:] = keep_dirs
        for name in files:
            rel = f"{relative_dir}/{name}" if relative_dir else name
            if rel in NEVER or _match(name, SKIP_FILES):
                continue
            if rel.startswith("output/") and not rel.startswith("output/agent/profiles/"):
                continue
            if mode == "migration" and _match(rel, MIGRATION_EXTRA_SKIP):
                continue
            if mode == "github":
                if _match(rel, GITHUB_SKIP):
                    continue
                if rel.startswith("models/") and name not in GITHUB_MODELS:
                    continue
            yield current / name, rel


MOVE_GUIDE = """# Költözés másik gépre

A csomag tartalma: a teljes `projekt` (forrás, tesztek, eszközök, addon, dokumentáció),
a tanult memória (`output/agent/profiles/`), a modellek (.pt/.onnx) és a TDB spawn katalógus.

**Nincs benne** (szándékosan):
- `config/wow_password.txt` és `config/wow_account.txt` – ezeket kézzel másold át;
- TensorRT `.engine` fájlok – csak NVIDIA-n futnak, a telepítő újraépíti őket;
- futásnaplók, live captures, tanító adathalmazok (`datasets/`, `runs/`).

## Lépések az új gépen
1. Csomagold ki például ide: `C:\\Users\\<név>\\Documents\\aipc\\projekt` (a mappanévben lehet szóköz).
2. Telepíts Python 3.13-at (64 bit, „Add to PATH”).
3. Futtasd az `INSTALL_WIZARD.bat`-ot, és nyomd meg a „Minden egyben telepítés” gombot:
   - Python-csomagok (AMD/Intel GPU-n `onnxruntime-directml`, NVIDIA-n CUDA torch),
   - WoW Retail mappa kiválasztása, addon telepítése,
   - navigációs adatok (maps → vmaps → mmaps) a TrinityCore extractorokkal,
   - YOLO modell az adott GPU-ra, automatikus indítás.
4. Másold át kézzel a `config/wow_account.txt` és `config/wow_password.txt` fájlt (ha az automatikus belépést használod).
5. Helyi MI (opcionális): telepítsd az Ollamát (https://ollama.com), majd
   `ollama pull qwen3:4b-instruct-2507-q4_K_M`. Indítás előtt: `ollama serve`.
6. WoW-ban kezdetben ugyanazt az ablakméretet és UI-méretezést használd, mint a régi gépen.
7. Első indítás: `START_AGENT.bat`, kiválasztod a WoW PID-et; a kötés-cache az addonból magától elkészül.
"""

README = """# WoW Retail AI agent (sandbox server)

Autonomous questing agent for World of Warcraft Retail 12.1 on a private sandbox server.
It reads the game through its own addon (pixel-strip telemetry), sees the 3D world with a
YOLO detector, plans with a shared WorldModel / planner / skill architecture and drives the
client with ordinary keyboard and mouse input for the selected process only. No memory
reading, injection or secret-value bypasses.

## Install
1. Python 3.13 (64-bit) on Windows 10/11.
2. Run `INSTALL_WIZARD.bat` → "Minden egyben telepítés" (all-in-one):
   Python packages (CUDA torch on NVIDIA, `onnxruntime-directml` on AMD/Intel), WoW addon,
   navigation data (maps/vmaps/mmaps via the TrinityCore extractors placed in `_retail_`),
   the YOLO model for this GPU and the start shortcuts.
3. Optional login file for unattended start: `config/wow_account.txt`, `config/wow_password.txt`
   (created by you, never committed – see `.gitignore`).
4. Optional local LLM for complex quest text: install Ollama and
   `ollama pull qwen3:4b-instruct-2507-q4_K_M` (see `config/ai_decision.json` → `semantic`).

## Run
`START_AGENT.bat` (GUI) or `AUTO_START.bat`. See `HOW_TO_USE.md`.

## Not included
- TensorRT engines (built per GPU by the wizard), training datasets and runs, personal agent
  memory and logs, the TrinityCore spawn catalog (`data/tdb_spawn_catalog.sqlite3`, optional).
- Recast/Detour sources: a prebuilt `native/bin/aipc_detour.dll` is included; to rebuild it,
  clone https://github.com/recastnavigation/recastnavigation into `native/recastnavigation`
  and build `native/detour_shim` with CMake.
- `weights/yolo26n.pt` (Ultralytics base weights, only for training; downloaded by Ultralytics).

## Tests
`python -m pytest tests`
"""

GITIGNORE_EXTRA = """
# Personal / per-machine (never commit)
config/wow_password.txt
config/wow_account.txt
config/local_env.bat
output/
datasets/
runs/
runs_*.log
weights/
*.engine
native/recastnavigation/
data/*.sqlite3
"""


def build_migration() -> Path:
    EXPORT.mkdir(exist_ok=True)
    target = EXPORT / f"AIPC_migration_{datetime.now():%Y%m%d-%H%M}.zip"
    count = size = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, rel in iter_files("migration"):
            archive.write(path, f"projekt/{rel}")
            count += 1
            size += path.stat().st_size
        archive.writestr("KOLTOZES.md", MOVE_GUIDE)
    print(f"migration: {count} files, {size/1e6:.0f} MB raw -> {target} ({target.stat().st_size/1e6:.0f} MB)")
    return target


def build_github(name: str = "wow-ai-agent") -> Path:
    target = EXPORT / "github" / name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    count = 0
    for path, rel in iter_files("github"):
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        count += 1
    # The repository README (edited on GitHub, 2026-10-05) lives in the
    # project; the built-in text is only for a project without one.
    if not (target / "README.md").exists():
        (target / "README.md").write_text(README, encoding="utf-8")
    gitignore = target / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    present = {line.strip() for line in existing.splitlines()}
    missing = [line for line in GITIGNORE_EXTRA.strip().splitlines()
               if line.strip() and not line.startswith("#") and line.strip() not in present]
    if missing:
        gitignore.write_text(existing.rstrip() + "\n\n# Personal / per-machine (never commit)\n"
                             + "\n".join(missing) + "\n", encoding="utf-8")
    # Public copy: no local Windows user name in paths.
    home = str(Path.home())
    for path in target.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".md", ".py", ".txt", ".json", ".bat", ".toc", ".lua"}:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            cleaned = (text.replace(home, r"C:\Users\<user>")
                       .replace(home.replace("\\", "/"), "C:/Users/<user>"))
            if cleaned != text:
                path.write_text(cleaned, encoding="utf-8")
    for rel in NEVER:
        assert not (target / rel).exists(), rel
    print(f"github: {count} files -> {target}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--migration", action="store_true")
    parser.add_argument("--github", action="store_true")
    args = parser.parse_args()
    if not (args.migration or args.github):
        parser.error("choose --migration and/or --github")
    if args.github:
        build_github()
    if args.migration:
        build_migration()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
