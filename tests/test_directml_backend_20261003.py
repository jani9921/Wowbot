"""AMD/Intel GPUs: ONNX model on DirectML (user 2026-10-03)."""
from types import SimpleNamespace

from wowbot.vision.world3d import directml


class _Session:
    def __init__(self, path, sess_options=None, providers=None):
        self.path, self.options, self.providers = path, sess_options, providers


def _fake_ort(providers):
    class Options:
        enable_mem_pattern = True
        execution_mode = None
    return SimpleNamespace(
        get_available_providers=lambda: providers, InferenceSession=_Session,
        SessionOptions=Options, ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="SEQ"))


def test_cpu_only_sessions_get_directml_first_when_installed():
    ort = _fake_ort(["DmlExecutionProvider", "CPUExecutionProvider"])
    assert directml.enable_directml_for_onnx(ort)
    session = ort.InferenceSession("m.onnx", None, ["CPUExecutionProvider"])
    assert session.providers == ["DmlExecutionProvider", "CPUExecutionProvider"]
    assert session.options.enable_mem_pattern is False and session.options.execution_mode == "SEQ"
    # An explicit CUDA request is left alone.
    cuda = ort.InferenceSession("m.onnx", None, ["CUDAExecutionProvider", "CPUExecutionProvider"])
    assert cuda.providers[0] == "CUDAExecutionProvider"


def test_without_directml_nothing_changes():
    ort = _fake_ort(["CPUExecutionProvider"])
    assert not directml.enable_directml_for_onnx(ort)
    assert ort.InferenceSession is _Session


def test_model_choice_prefers_engine_then_onnx_then_pt(monkeypatch):
    from wowbot.vision.world3d import learned_detector as ld
    monkeypatch.delenv("AIPC_WORLD3D_MODEL", raising=False)
    monkeypatch.setattr(ld, "_cuda_available", lambda: False)
    monkeypatch.setattr(directml, "directml_available", lambda: True)
    assert ld.default_runtime_model_path().suffix == ".onnx"
    monkeypatch.setattr(directml, "directml_available", lambda: False)
    assert ld.default_runtime_model_path().suffix == ".pt"
    monkeypatch.setattr(ld, "_cuda_available", lambda: True)
    assert ld.default_runtime_model_path().suffix == ".engine"


def test_ultralytics_never_reinstalls_plain_onnxruntime_over_directml(monkeypatch):
    import ultralytics.nn.backends.onnx as backend
    calls = []
    monkeypatch.setattr(backend, "check_requirements", lambda req, *a, **k: calls.append(req) or False)
    directml._guard_ultralytics_autoinstall()
    assert backend.check_requirements(("onnx", "onnxruntime")) is True
    assert calls == []
    backend.check_requirements(("lap",))
    assert calls == [("lap",)]
