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


def test_bounded_test_on_running_full_ai_gets_a_deadline():
    # Issue #74: a bounded trial started while FULL_AI already runs must
    # still expire; mode() returns early so the arming branch never sets it.
    import time
    runtime = SimpleNamespace(
        agent=SimpleNamespace(mode=Mode.FULL_AI, action_budget=None),
        arm_at=None, test_seconds=None, test_deadline=None,
        test_dialog_grace_deadline=None, _test_dialog_grace_enabled=False,
        _test_dialog_grace_used=True,
        live_capture=SimpleNamespace(rotate=lambda: None),
    )

    before = time.monotonic()
    RuntimeControl(runtime).test_step(actions=60, seconds=30)

    assert runtime.agent.mode == Mode.FULL_AI
    assert runtime.agent.action_budget == 60
    assert runtime.test_deadline is not None
    assert before+30 <= runtime.test_deadline <= time.monotonic()+30
    assert runtime._test_dialog_grace_used is False
