"""Live 2026-10-04 00:03: a turn-in search MOVE started at 00:03:22; at
00:03:29 FULL_AI suspended on "stale" telemetry and never resumed although
the pixel strip streamed at ~38 Hz.  The FAST lane consumed every packet of
the active reach without touching world receive-liveness, and empty polls
between packets ran medium ticks that kept pushing the 1 s reach window, so
no medium tick ever ingested a packet."""
from test_agent_core import binding_file, state
from test_agent_runtime import Sensor

from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Mode
from wowbot.agent.runtime import AgentRuntime

SUSPENDED = "telemetry_suspended_waiting_for_stable_recovery"


def _run(tmp_path, gap=None, until=20.):
    sensor, executor = Sensor(), RecordingExecutor()
    runtime = AgentRuntime(42, binding_file(tmp_path), tmp_path / "output",
                           sensor=sensor, executor=executor, vision=False)
    reasons = []
    try:
        runtime.agent.set_goal("Menj oda", 1., {"destination": {"map_id": 1609, "x": .5, "y": .4}})
        runtime.agent.set_mode(Mode.FULL_AI)
        runtime.agent.tick(state(1.), 1.)
        assert runtime.agent.pending.proposal.skill == "MOVE"
        at, sequence = 1., 0
        while at < until:
            at = round(at + .026, 3)
            if not (gap and gap[0] <= at < gap[1]) and int(at * 1000) % 3:
                sequence += 1
                sensor.payload = state(at, transport_kind="FAST", telemetry_lane="FAST_STATE",
                                       fast_sequence=sequence, position={"x": .5, "y": .499},
                                       movement={"speed": 0., "moving": False})
            result = runtime.step(at)
            reasons.append((at, result["mode"], (result.get("decision") or {}).get("reason")))
    finally:
        runtime.close()
    return reasons


def test_streaming_fast_packets_keep_an_active_reach_live(tmp_path):
    assert not any(reason == SUSPENDED for _at, _mode, reason in _run(tmp_path, until=12.))


def test_reach_resumes_after_a_real_telemetry_gap(tmp_path):
    reasons = _run(tmp_path, gap=(5., 12.), until=16.)
    assert any(reason == SUSPENDED for at, _mode, reason in reasons if 11. <= at < 12.)
    assert all(mode == "FULL_AI" and reason != SUSPENDED
               for at, mode, reason in reasons if at >= 14.)
