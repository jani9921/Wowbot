"""TensorRT engine <-> GPU compatibility fingerprint (issues #19, #86).

A TensorRT ``.engine`` is specific to the GPU, compute capability and the
TensorRT/CUDA build that produced it, but it was selected by file existence
alone.  The installer now records the build fingerprint in a sidecar JSON
next to the engine and both the installer and the runtime compare it with
the current machine before trusting the engine.
"""
from __future__ import annotations

import json
from pathlib import Path

FINGERPRINT_SUFFIX = ".fingerprint.json"
FIELDS = ("gpu_name", "compute_capability", "cuda", "tensorrt")


def sidecar(engine: str | Path) -> Path:
    engine = Path(engine)
    return engine.with_name(engine.name + FINGERPRINT_SUFFIX)


def probe_fingerprint() -> dict | None:
    """Current NVIDIA/CUDA/TensorRT identity; None without a usable CUDA GPU."""
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        major, minor = torch.cuda.get_device_capability(0)
        result = {"gpu_name": str(torch.cuda.get_device_name(0)),
                  "compute_capability": f"{major}.{minor}",
                  "cuda": str(torch.version.cuda), "tensorrt": None}
    except Exception:
        return None
    try:
        import tensorrt
        result["tensorrt"] = str(tensorrt.__version__)
    except Exception:
        pass
    return result


def write_fingerprint(engine: str | Path, fingerprint: dict | None) -> bool:
    if not isinstance(fingerprint, dict):
        return False
    sidecar(engine).write_text(json.dumps({key: fingerprint.get(key) for key in FIELDS},
                                          sort_keys=True), encoding="utf-8")
    return True


def read_fingerprint(engine: str | Path) -> dict | None:
    try:
        value = json.loads(sidecar(engine).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def engine_status(engine: str | Path, current: dict | None) -> str:
    """``verified`` | ``unverified`` (no sidecar) | ``probe_failed`` |
    ``mismatch:<field>`` | ``missing``."""
    if not Path(engine).is_file():
        return "missing"
    recorded = read_fingerprint(engine)
    if recorded is None:
        return "unverified"
    if not isinstance(current, dict):
        return "probe_failed"
    for key in FIELDS:
        if recorded.get(key) is not None and recorded.get(key) != current.get(key):
            return f"mismatch:{key}"
    return "verified"


def build_script(model: str | Path, engine: str | Path, project: str | Path) -> str:
    """Python code for the installer subprocess: export, then record."""
    return ("import sys; sys.path.insert(0, %r); "
            "from ultralytics import YOLO; "
            "YOLO(%r).export(format='engine', imgsz=640, half=True, batch=1, "
            "simplify=True, dynamic=False, device=0); "
            "from wowbot.install.engine_fingerprint import probe_fingerprint, write_fingerprint; "
            "sys.exit(0 if write_fingerprint(%r, probe_fingerprint()) else 3)"
            % (str(Path(project) / "src"), str(model), str(engine)))
