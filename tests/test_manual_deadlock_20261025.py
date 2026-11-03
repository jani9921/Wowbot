"""MANUAL froze the GUI: lock-order deadlock (live 2026-10-25 11:00:47).

The agent thread held the memory transaction (``memory.batch()`` around the
tick) and waited for the engine lock in ``tick()``; the GUI's MANUAL ran
``set_mode`` holding the engine lock and waited for the memory transaction to
record the cancelled skill.  Both threads stayed blocked; the user killed the
process.  The tick now takes the engine lock before the memory transaction.
"""
from contextlib import contextmanager
import threading

from test_agent_core import binding_file, state
from test_agent_runtime import Sensor

from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.runtime import AgentRuntime


def test_the_tick_holds_the_engine_lock_before_the_memory_transaction(tmp_path):
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=Sensor(), executor=RecordingExecutor(), vision=False)
    held = []
    original = runtime.memory.batch

    @contextmanager
    def batch():
        probe = []
        thread = threading.Thread(target=lambda: probe.append(runtime.agent.lock.acquire(timeout=.05)))
        thread.start()
        thread.join()
        if probe[0]:
            runtime.agent.lock.release()
        held.append(not probe[0])            # another thread could not take it: we hold it
        with original():
            yield
    runtime.memory.batch = batch
    try:
        runtime.agent.set_goal("Menj oda", 1., {"destination": {"map_id": 1609, "x": .5, "y": .4}})
        runtime.sensor.payload = state(1.)
        runtime.step(1.)
    finally:
        runtime.close()
    assert held and all(held)
