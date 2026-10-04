"""Pure checks and command builders for the installation wizard.

Nothing here launches a process or changes a file except the explicit
``install_addon`` / ``write_local_env`` / ``update_gui_config`` helpers, which
the wizard calls only after a user click.  Navigation data comes from the
TrinityCore extractors in the Retail folder (user 2026-10-02: maps, vmaps and
mmaps are all extracted there and read from there; no zip).
"""
from __future__ import annotations

import importlib.metadata
import filecmp
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

DEFAULT_RETAIL = Path(r"C:\Program Files (x86)\World of Warcraft\_retail_")
REQUIRED_CLIENT_PREFIX = "12.1."
EXTRACTORS = ("mapextractor.exe", "vmap4extractor.exe", "vmap4assembler.exe", "mmaps_generator.exe")
EXILES_REACH_MAP_ID = 2175
# Windows STATUS_DLL_NOT_FOUND as a process exit code.
DLL_NOT_FOUND_EXIT_CODES = frozenset({0xC0000135, -1073741515})

# (import name, pip distribution, purpose); optional ones never block.
REQUIRED_PACKAGES = (
    ("numpy", "numpy", "alap számítás"),
    ("cv2", "opencv-python", "képfeldolgozás"),
    ("PIL", "Pillow", "képek"),
    ("dxcam", "dxcam", "DXGI képernyő-capture"),
    ("ultralytics", "ultralytics", "YOLO felismerés"),
    ("lap", "lap", "BoT-SORT követés"),
    ("torch", "torch", "neurális háló (GPU)"),
)
OPTIONAL_PACKAGES = (
    ("tensorrt", "tensorrt", "gyorsított YOLO engine (opcionális)"),
    ("onnxruntime", "onnxruntime-directml", "YOLO AMD/Intel GPU-n (DirectML)"),
    ("lupa", "lupa", "addon Lua-tesztek (fejlesztés)"),
    ("pytest", "pytest", "tesztek (fejlesztés)"),
)
TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu128"


def _numeric_name(path: Path) -> int | None:
    stem = path.name.split(".", 1)[0]
    return int(stem) if stem.isdigit() else None


def client_version(retail: Path) -> str | None:
    """Version from the launcher's ``.build.info`` next to ``_retail_``."""
    info = Path(retail).parent / ".build.info"
    try:
        lines = info.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if len(lines) < 2:
        return None
    header = [column.split("!", 1)[0] for column in lines[0].split("|")]
    if "Version" not in header:
        return None
    column = header.index("Version")
    for line in lines[1:]:
        values = line.split("|")
        if len(values) > column and values[column].strip():
            return values[column].strip()
    return None


def is_writable(folder: Path) -> bool:
    probe = Path(folder) / ".aipc_install_probe"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def validate_retail(retail: Path) -> dict:
    retail = Path(retail)
    version = client_version(retail)
    extractors = {name: (retail / name).is_file() for name in EXTRACTORS}
    result = {
        "path": str(retail),
        "exists": retail.is_dir(),
        "wow_exe": (retail / "Wow.exe").is_file(),
        "client_version": version,
        "version_ok": bool(version and version.startswith(REQUIRED_CLIENT_PREFIX)),
        "extractors": extractors,
        "extractors_ok": all(extractors.values()),
        "dll_count": len(list(retail.glob("*.dll"))) if retail.is_dir() else 0,
        "addons_dir": str(retail / "Interface" / "AddOns"),
        "writable": retail.is_dir() and is_writable(retail),
    }
    # Extractors are needed only when navigation data must be generated. A
    # machine with complete maps/vmaps/mmaps can run without the executables.
    result["ok"] = bool(result["exists"] and result["wow_exe"] and result["version_ok"])
    return result


def detect_retail(candidates=()) -> Path | None:
    for candidate in (*candidates, DEFAULT_RETAIL,
                      Path(r"C:\Program Files\World of Warcraft\_retail_")):
        if candidate and (Path(candidate) / "Wow.exe").is_file():
            return Path(candidate)
    return None


def toc_version(addon_dir: Path) -> str | None:
    toc = Path(addon_dir) / "AIPlayerControllerExport.toc"
    try:
        text = toc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"^## Version:\s*(\S+)", text, re.MULTILINE)
    return match[1] if match else None


def addon_status(project: Path, retail: Path) -> dict:
    source = Path(project) / "addon" / "AIPlayerControllerExport-12.1.0"
    target = Path(retail) / "Interface" / "AddOns" / "AIPlayerControllerExport"
    project_version, installed = toc_version(source), toc_version(target)
    files_match = source.is_dir() and all(
        (target / item.name).is_file()
        and filecmp.cmp(item, target / item.name, shallow=False)
        for item in source.iterdir() if item.is_file())
    return {"source": str(source), "target": str(target),
            "project_version": project_version, "installed_version": installed,
            "up_to_date": bool(project_version and project_version == installed and files_match)}


def install_addon(project: Path, retail: Path) -> list[str]:
    """Copy the versioned 12.1.0 addon over the installed one (files only)."""
    source = Path(project) / "addon" / "AIPlayerControllerExport-12.1.0"
    target = Path(retail) / "Interface" / "AddOns" / "AIPlayerControllerExport"
    if not source.is_dir():
        raise FileNotFoundError(source)
    target.mkdir(parents=True, exist_ok=True)
    copied = []
    for item in sorted(source.iterdir()):
        if item.is_file():
            shutil.copy2(item, target / item.name)
            copied.append(item.name)
    return copied


def _ids(folder: Path, pattern: str, *, dirs: bool = False) -> set[int]:
    if not folder.is_dir():
        return set()
    found = set()
    with os.scandir(folder) as entries:
        for entry in entries:
            if dirs and entry.is_dir() and entry.name.isdigit():
                found.add(int(entry.name))
            elif not dirs and entry.is_file() and entry.name.endswith(pattern):
                value = _numeric_name(Path(entry.name))
                if value is not None:
                    found.add(value)
    return found


def navigation_status(retail: Path, focus_maps=(EXILES_REACH_MAP_ID,)) -> dict:
    """Which map IDs have maps / vmaps / mmaps in the Retail folder."""
    retail = Path(retail)
    maps = _ids(retail / "maps", ".tilelist")
    vmaps = {map_id for map_id in _ids(retail / "vmaps", "", dirs=True)
             if (retail / "vmaps" / f"{map_id:04d}" / f"{map_id:04d}.vmtree").is_file()}
    mmaps = _ids(retail / "mmaps", ".mmap")
    return {
        "maps_count": len(maps), "vmaps_count": len(vmaps), "mmaps_count": len(mmaps),
        "mmaps_dir": str(retail / "mmaps"),
        "buildings_present": (retail / "Buildings").is_dir(),
        "focus": {map_id: {"maps": map_id in maps, "vmaps": map_id in vmaps,
                           "mmaps": map_id in mmaps} for map_id in focus_maps},
        "mmap_ids": sorted(mmaps),
    }


def required_navigation_steps(status: dict, map_id: int = EXILES_REACH_MAP_ID) -> list[str]:
    """Check the selected zone, not merely whether *some* zone was extracted."""
    focus = status.get("focus", {}).get(map_id, {})
    return [name for name in ("maps", "vmaps", "mmaps") if not focus.get(name)]


def installation_issues(project: Path, retail: Path, vendor: str, *,
                        torch_cuda: bool = False, directml: bool = False) -> list[str]:
    """Final fail-closed check used by the all-in-one flow and offline tests."""
    issues = []
    client = validate_retail(retail)
    if not client["ok"]:
        issues.append("WoW Retail 12.1.x nem ellenőrzött")
    if not addon_status(project, retail)["up_to_date"]:
        issues.append("addon hiányzik vagy eltér a projekt verziójától")
    missing = required_navigation_steps(navigation_status(retail))
    if missing:
        issues.append("Exile's Reach navigáció hiányzik: " + ", ".join(missing))
    model = runtime_model_status(project, vendor, torch_cuda=torch_cuda, directml=directml)
    if not model["pt"]:
        issues.append("a futásidejű YOLO .pt modell hiányzik")
    if vendor == "NVIDIA" and model["backend"] != "TensorRT":
        issues.append("NVIDIA TensorRT engine nem épült meg erre a gépre")
    if vendor in {"AMD", "INTEL"} and model["backend"] != "DirectML":
        issues.append(f"{vendor} DirectML modell/provider nem kész")
    return issues


def parse_map_ids(text: str) -> list[int]:
    """'2175, 0 1' -> [2175, 0, 1]; raises ValueError on anything else."""
    values = [part for part in re.split(r"[\s,;]+", str(text).strip()) if part]
    if not values:
        raise ValueError("adj meg legalább egy térkép-azonosítót")
    result = []
    for value in values:
        if not value.isdigit():
            raise ValueError(f"érvénytelen térkép-azonosító: {value}")
        if int(value) not in result:
            result.append(int(value))
    return result


def extraction_commands(step: str, retail: Path, *, map_ids=None, threads: int = 4) -> list[list[str]]:
    """Exactly what the TrinityCore ``extractor.bat`` runs, made non-interactive.

    ``maps``  -> mapextractor (cameras, dbc, gt, maps)
    ``vmaps`` -> vmap4extractor, then vmap4assembler Buildings vmaps
    ``mmaps`` -> mmaps_generator per selected map, or all maps when ``map_ids`` is None
    """
    retail = Path(retail)
    threads = max(1, int(threads))
    if step == "maps":
        return [[str(retail / "mapextractor.exe")]]
    if step == "vmaps":
        return [[str(retail / "vmap4extractor.exe")],
                [str(retail / "vmap4assembler.exe"), "Buildings", "vmaps"]]
    if step == "mmaps":
        base = [str(retail / "mmaps_generator.exe")]
        options = ["--silent", "--threads", str(threads)]
        if map_ids is None:
            return [base + options]
        return [base + [str(int(map_id))] + options for map_id in map_ids]
    raise ValueError(step)


def explain_exit_code(code: int | None) -> str:
    if code == 0:
        return "kész"
    if code in DLL_NOT_FOUND_EXIT_CODES:
        return "hiányzó DLL: az extractor DLL-jeinek a _retail_ mappában kell lenniük"
    return f"hibakód: {code}"


def package_status() -> dict:
    """Installed distribution versions; importing is left to the caller."""
    def version(dist: str) -> str | None:
        try:
            return importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            return None
    return {"required": [(module, dist, purpose, version(dist)) for module, dist, purpose in REQUIRED_PACKAGES],
            "optional": [(module, dist, purpose, version(dist)) for module, dist, purpose in OPTIONAL_PACKAGES]}


def gpu_vendor(names: list[str] | None = None) -> str:
    """"NVIDIA", "AMD", "INTEL" or "" from the Windows video controllers."""
    if names is None:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_VideoController).Name"],
                capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            names = [line.strip() for line in out.stdout.splitlines() if line.strip()]
        except (OSError, subprocess.SubprocessError):
            names = []
    joined = " ".join(names).upper()
    for vendor, tokens in (("NVIDIA", ("NVIDIA", "GEFORCE", "RTX", "QUADRO")),
                           ("AMD", ("AMD", "RADEON")), ("INTEL", ("INTEL", "ARC"))):
        if any(token in joined for token in tokens):
            return vendor
    return ""


def _python_boolean_probe(python: str, expression: str) -> bool:
    """Probe the interpreter the wizard will actually use, not this process."""
    try:
        result = subprocess.run(
            [python, "-c", f"print(bool({expression}))"], capture_output=True,
            text=True, timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "True"


def probe_torch_cuda(python: str = sys.executable) -> bool:
    return _python_boolean_probe(python, "__import__('torch').cuda.is_available()")


def probe_directml(python: str = sys.executable) -> bool:
    return _python_boolean_probe(
        python, "'DmlExecutionProvider' in __import__('onnxruntime').get_available_providers()")


def probe_tensorrt(python: str = sys.executable) -> bool:
    return _python_boolean_probe(
        python, "__import__('tensorrt').Builder(__import__('tensorrt').Logger()) is not None")


def runtime_model_status(project: Path, vendor: str, *, torch_cuda: bool = False,
                         directml: bool = False) -> dict:
    """Predict the default YOLO selection from local files and provider probes."""
    models = Path(project) / "models"
    stem = "world3d_units_3class_v10_e65"
    pt, onnx, engine = (models / f"{stem}{suffix}"
                        for suffix in (".pt", ".onnx", ".engine"))
    if vendor == "NVIDIA" and torch_cuda and engine.is_file():
        backend = "TensorRT"
        selected = engine
    elif vendor == "NVIDIA" and torch_cuda and pt.is_file():
        backend = "PyTorch CUDA"
        selected = pt
    elif vendor in {"AMD", "INTEL"} and directml and onnx.is_file():
        backend = "DirectML"
        selected = onnx
    elif pt.is_file():
        backend = "CPU"
        selected = pt
    else:
        backend = "MISSING"
        selected = None
    return {"backend": backend, "pt": pt.is_file(), "onnx": onnx.is_file(),
            "engine": engine.is_file(),
            "model_name": selected.name if selected else None,
            "accelerated": backend in {"TensorRT", "PyTorch CUDA", "DirectML"}}


def directml_command(python: str, status: dict) -> list[str] | None:
    """AMD/Intel: ONNX Runtime with DirectML runs the YOLO model on the GPU.

    Measured 2026-10-03 on the same model/frame: 15 ms (DirectML) vs 251 ms
    (CPU), identical detections.  Never alongside onnxruntime-gpu (NVIDIA).
    """
    installed = any(dist == "onnxruntime-directml" and version
                    for _m, dist, _p, version in status["optional"])
    return None if installed else [python, "-m", "pip", "install", "onnxruntime-directml"]


def pip_commands(python: str, status: dict, *, gpu: bool, torch_cuda: bool | None) -> list[list[str]]:
    """Install only what is missing; CUDA torch comes from the PyTorch index."""
    commands = []
    missing = [dist for _module, dist, _purpose, version in status["required"]
               if version is None and dist != "torch"]
    if missing:
        commands.append([python, "-m", "pip", "install", *missing])
    torch_version = next(version for _m, dist, _p, version in status["required"] if dist == "torch")
    if torch_version is None:
        command = [python, "-m", "pip", "install", "torch", "torchvision"]
        commands.append(command + (["--index-url", TORCH_CUDA_INDEX] if gpu else []))
    elif gpu and torch_cuda is False:
        commands.append([python, "-m", "pip", "install", "--upgrade", "--force-reinstall", "--no-deps",
                         "torch", "torchvision", "--index-url", TORCH_CUDA_INDEX])
    return commands


def write_local_env(project: Path, retail: Path) -> Path:
    """``config/local_env.bat``: the START_*.bat files call it when present."""
    retail = Path(retail)
    path = Path(project) / "config" / "local_env.bat"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["@rem Generated by the installation wizard. Navigation data extracted in _retail_.",
             f'set "WOWBOT_WORLD_DATA_PATH={retail}"',
             f'set "WOWBOT_MMAP_PATH={retail / "mmaps"}"',
             # AUTO_START.bat (tools/wow_auto_start.py) starts this client.
             f'set "AIPC_WOW_EXE={retail / "Wow.exe"}"']
    if not str(retail).isascii():
        lines.insert(1, "@chcp 65001 >nul")   # cmd reads .bat files in the console code page
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return path


def update_gui_config(path: Path, mmap_dir: Path) -> dict:
    """Point the agent GUI at the extracted mmaps folder; keep every other key."""
    path = Path(path)
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    data["mmap_path"] = str(mmap_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


ACCOUNT_FILE = Path("config") / "wow_account.txt"
PASSWORD_FILE = Path("config") / "wow_password.txt"


def autostart_status(project: Path) -> dict:
    """Whether AUTO_START can log in unattended (files exist and are not empty)."""
    def first_line(relative: Path) -> str:
        try:
            lines = (Path(project) / relative).read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            return ""
        return lines[0].strip() if lines else ""
    account = first_line(ACCOUNT_FILE)
    return {"account": account, "password_saved": bool(first_line(PASSWORD_FILE))}


def write_autostart_login(project: Path, account: str, password: str | None) -> list[Path]:
    """Save the login the USER typed into the wizard (local files only).

    The password stays in ``config/wow_password.txt`` on this PC in plain
    text; an empty password keeps the existing file unchanged.
    """
    written = []
    config = Path(project) / "config"
    config.mkdir(parents=True, exist_ok=True)
    if account.strip():
        (Path(project) / ACCOUNT_FILE).write_text(account.strip() + "\n", encoding="utf-8")
        written.append(Path(project) / ACCOUNT_FILE)
    if password:
        (Path(project) / PASSWORD_FILE).write_text(password + "\n", encoding="utf-8")
        written.append(Path(project) / PASSWORD_FILE)
    return written


SHORTCUTS = (("AIPC Agent - automatikus indítás", "AUTO_START.bat"),
             ("AIPC Agent - kézi indítás", "START_AGENT.bat"),
             ("AIPC Agent - telepítő", "INSTALL_WIZARD.bat"))


def shortcut_command(project: Path) -> list[str]:
    """PowerShell command creating desktop shortcuts to the start files."""
    parts = ["$s = New-Object -ComObject WScript.Shell",
             "$d = [Environment]::GetFolderPath('Desktop')"]
    for title, target in SHORTCUTS:
        path = Path(project) / target
        parts += [f"$l = $s.CreateShortcut((Join-Path $d '{title}.lnk'))",
                  f"$l.TargetPath = '{path}'",
                  f"$l.WorkingDirectory = '{Path(project)}'",
                  "$l.Save()"]
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "; ".join(parts)]
