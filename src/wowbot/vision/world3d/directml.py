"""DirectML for the ONNX YOLO model on non-NVIDIA GPUs (user 2026-10-03: AMD).

CUDA/TensorRT exist only on NVIDIA.  ``onnxruntime-directml`` runs ONNX models
on any DirectX 12 GPU (AMD, Intel, NVIDIA).  Ultralytics' ONNX backend only
chooses CUDA, CoreML or CPU providers, so when it asks for the CPU provider and
DirectML is installed, this adapter puts ``DmlExecutionProvider`` first (CPU
stays as the fallback).  DirectML requires memory patterns off and sequential
execution, which are set on the session options it receives.
"""
from __future__ import annotations

import os

DML = "DmlExecutionProvider"
_ENABLED = False


def directml_available() -> bool:
    try:
        import onnxruntime
    except ImportError:
        return False
    try:
        return DML in onnxruntime.get_available_providers()
    except Exception:
        return False


def enable_directml_for_onnx(onnxruntime_module=None) -> bool:
    """Make CPU-only ONNX sessions use DirectML first; idempotent."""
    global _ENABLED
    if os.environ.get("AIPC_DIRECTML", "1").strip().lower() in {"0", "false", "off", "no"}:
        return False
    if onnxruntime_module is None:
        try:
            import onnxruntime as onnxruntime_module
        except ImportError:
            return False
    if DML not in onnxruntime_module.get_available_providers():
        return False
    if getattr(onnxruntime_module.InferenceSession, "_aipc_directml", False):
        _ENABLED = True
        return True
    original = onnxruntime_module.InferenceSession

    class DirectMLInferenceSession(original):
        _aipc_directml = True

        def __init__(self, path_or_bytes, sess_options=None, providers=None, *args, **kwargs):
            if providers is None or list(providers) == ["CPUExecutionProvider"]:
                providers = [DML, "CPUExecutionProvider"]
                if sess_options is None:
                    sess_options = onnxruntime_module.SessionOptions()
                sess_options.enable_mem_pattern = False
                sess_options.execution_mode = onnxruntime_module.ExecutionMode.ORT_SEQUENTIAL
            super().__init__(path_or_bytes, sess_options, providers, *args, **kwargs)

    onnxruntime_module.InferenceSession = DirectMLInferenceSession
    _guard_ultralytics_autoinstall()
    _ENABLED = True
    return True


def _guard_ultralytics_autoinstall() -> None:
    """Keep Ultralytics from pip-installing plain ``onnxruntime``.

    Its ONNX backend requires the distribution named "onnxruntime"; with only
    ``onnxruntime-directml`` present it would auto-install the CPU package
    over it and DirectML would be gone.  The DirectML build provides the
    ``onnxruntime`` module, and ``onnx`` is not needed for inference.
    """
    try:
        import ultralytics.nn.backends.onnx as backend
    except ImportError:
        return
    original = getattr(backend, "check_requirements", None)
    if original is None or getattr(original, "_aipc_directml", False):
        return

    def guarded(requirements, *args, **kwargs):
        names = requirements if isinstance(requirements, (tuple, list)) else (requirements,)
        if any(str(name).split("<")[0].split(">")[0].split("=")[0].strip()
               in {"onnx", "onnxruntime", "onnxruntime-gpu"} for name in names):
            return True
        return original(requirements, *args, **kwargs)

    guarded._aipc_directml = True
    backend.check_requirements = guarded
