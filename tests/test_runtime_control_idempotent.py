from types import SimpleNamespace

from wowbot.agent.models import Mode
from wowbot.agent.runtime_control import RuntimeControl


def test_repeated_full_ai_request_is_idempotent_while_safety_is_suspended():
    calls = []
    runtime = SimpleNamespace(
        agent=SimpleNamespace(mode=Mode.FULL_AI),
        arm_at=None,
        live_capture=SimpleNamespace(rotate=lambda: calls.append("rotate")),
    )

    RuntimeControl(runtime).mode("FULL_AI")

    assert calls == []
    assert runtime.agent.mode == Mode.FULL_AI
