import queue
import threading
import time
from types import SimpleNamespace

from wowbot.agent import gui


class _Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def test_connect_builds_slow_telemetry_runtime_off_tk_thread(tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    runtime_options = {}

    class SlowRuntime:
        def __init__(self, *_args, **_kwargs):
            runtime_options.update(_kwargs)
            entered.set()
            assert release.wait(2.)
            self.started = False

        def goal(self, *_args):
            pass

        def start(self):
            self.started = True

        def close(self):
            pass

    monkeypatch.setattr(gui, "AgentRuntime", SlowRuntime)
    monkeypatch.setattr("tools.wow_window.find_visible_wow_windows",
                        lambda: [SimpleNamespace(pid=42)])
    monkeypatch.setattr(
        "wowbot.vision.world3d.learned_detector.default_runtime_model_path",
        lambda: None)
    window = gui.AgentWindow.__new__(gui.AgentWindow)
    window.output = tmp_path
    window.runtime = None
    window.pid = _Value("42")
    window.cache = _Value(str(tmp_path / "bindings-cache.wtf"))
    window.mmap_path = _Value("")
    window.ollama = _Value(True)  # legacy saved widget state must have no effect
    window.model = _Value("test")
    window.goal_text = _Value("Questelj")
    window.parameters = _Value("{}")
    window.summary = _Value("")
    window._connect_thread = None
    window._connect_results = queue.SimpleQueue()
    window._connect_generation = 0
    window._closing = False

    started = time.perf_counter()
    window.connect()
    elapsed = time.perf_counter() - started

    assert elapsed < .1
    assert entered.wait(1.)
    assert window.runtime is None
    assert "folyamatban" in window.summary.value
    release.set()
    window._connect_thread.join(2.)
    window._finish_connections()
    assert window.runtime is not None
    assert window.runtime.started is True
    assert runtime_options["ollama"] == {"enabled": False}


def test_full_ai_mode_waits_for_runtime_lock_off_tk_thread():
    entered = threading.Event()
    release = threading.Event()

    class SlowControlRuntime:
        def mode(self, requested):
            assert requested == "FULL_AI"
            entered.set()
            assert release.wait(2.)

    window = gui.AgentWindow.__new__(gui.AgentWindow)
    window.runtime = SlowControlRuntime()
    window.summary = _Value("")
    window._control_thread = None
    window._control_results = queue.SimpleQueue()
    window._control_started_at = None
    window._control_label = None
    window._closing = False

    started = time.perf_counter()
    window.mode("FULL_AI")
    elapsed = time.perf_counter() - started

    assert elapsed < .1
    assert entered.wait(1.)
    assert "folyamatban" in window.summary.value.lower()
    release.set()
    window._control_thread.join(2.)
    window._finish_runtime_actions()
    assert window._control_thread is None
