"""Live 2026-11-02 16:00: after a logout/login in the same capture, walking
(and the corpse run) went stop-go at ~3 yd/s.

The packet baseline kept its session (same capture, same character) and the
medium tick renamed each addon sample to it; the parallel FAST control pump
read the raw sample, saw the addon's new session and stopped every sample as
"session_changed".  Both lanes now name the sample the same way."""
from types import SimpleNamespace

from wowbot.agent.models import Mode
from wowbot.agent.parallel_runtime import ParallelRuntimePump
from wowbot.session_context import BaselineState, SessionContextProvider


def provider(source="PACKET_BASELINE"):
    value = SessionContextProvider.__new__(SessionContextProvider)
    value.process = SimpleNamespace(selected_pid=7)
    value.state, value.source = BaselineState.READY, source
    value.context = SimpleNamespace(as_dict=lambda: {"session_id": "old-session"})
    return value


def test_the_packet_baseline_session_names_a_raw_fast_sample():
    assert provider().session_alias({"session_id": "new-addon-session", "x": 1})["session_id"] == "old-session"
    assert provider("ADDON_MIGRATION").session_alias({"session_id": "new"})["session_id"] == "new"


def test_the_parallel_pump_hands_the_renamed_sample_to_parallel_control():
    seen = []
    agent = SimpleNamespace(mode=Mode.FULL_AI, parallel_control=SimpleNamespace(
        tick=lambda payload, received, vision, now: seen.append(payload) or {}))
    runtime = SimpleNamespace(
        agent=agent, executor=SimpleNamespace(cancelled=None, backend=None),
        test_deadline=None, test_dialog_grace_deadline=None,
        sensor=SimpleNamespace(peek_latest=lambda now: ({"session_id": "new-addon-session"}, now)),
        perception=None, packet_telemetry=SimpleNamespace(session_provider=provider()))
    pump = ParallelRuntimePump.__new__(ParallelRuntimePump)
    pump.runtime = runtime
    pump.wake_medium = SimpleNamespace(set=lambda: None)
    pump.step(10.)
    assert seen and seen[0]["session_id"] == "old-session"
