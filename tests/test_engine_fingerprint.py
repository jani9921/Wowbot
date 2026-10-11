"""Issues #19/#86: TensorRT engine <-> GPU fingerprint (no GPU needed)."""
from wowbot.install import engine_fingerprint as fp
from wowbot.vision.world3d import learned_detector as ld

HERE = {"gpu_name": "RTX 4070", "compute_capability": "8.9", "cuda": "12.8", "tensorrt": "10.3"}


def test_status_values(tmp_path):
    engine = tmp_path / "m.engine"
    assert fp.engine_status(engine, HERE) == "missing"
    engine.write_bytes(b"e")
    assert fp.engine_status(engine, HERE) == "unverified"
    fp.write_fingerprint(engine, HERE)
    assert fp.engine_status(engine, HERE) == "verified"
    assert fp.engine_status(engine, None) == "probe_failed"
    assert fp.engine_status(engine, {**HERE, "tensorrt": "8.6"}) == "mismatch:tensorrt"


def test_runtime_skips_an_engine_recorded_for_another_gpu(tmp_path, monkeypatch):
    models = tmp_path / "models"
    models.mkdir()
    engine = models / ld.RUNTIME_ENGINE_NAME
    engine.write_bytes(b"e")
    monkeypatch.delenv("AIPC_WORLD3D_MODEL", raising=False)
    monkeypatch.setattr(ld, "_cuda_available", lambda: True)
    monkeypatch.setattr(fp, "probe_fingerprint", lambda: HERE)
    # default_runtime_model_path looks in parents[4] / "models".
    monkeypatch.setattr(ld, "__file__", str(tmp_path / "a" / "b" / "c" / "d" / "learned_detector.py"))
    assert ld.default_runtime_model_path() == engine          # legacy: no sidecar, still tried
    fp.write_fingerprint(engine, {**HERE, "gpu_name": "GTX 1060"})
    assert ld.default_runtime_model_path().name == ld.RUNTIME_MODEL_NAME
    fp.write_fingerprint(engine, HERE)
    assert ld.default_runtime_model_path() == engine
