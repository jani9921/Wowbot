from types import SimpleNamespace

from wowbot.runtime.active_skill import ActiveSkillRuntime
from wowbot.runtime.contracts import FailureReason, Intent, SkillResult, SkillStatus
from wowbot.runtime.skill_contract import SkillBaseContract, SkillContractAdapter


def _state():
    runtime = ActiveSkillRuntime()
    return runtime.start(intent=Intent("TARGET"), attempt=SimpleNamespace(deadline=5), now=1.0)


def test_skill_adapter_implements_complete_contract_without_owning_state():
    calls = []
    adapter = SkillContractAdapter(
        lambda state, world: calls.append(("start", state.runtime_id)) or SkillResult(SkillStatus.RUNNING),
        lambda state, world, now: calls.append(("tick", now)) or SkillResult(SkillStatus.SUCCESS))
    assert isinstance(adapter, SkillBaseContract)
    state = _state()
    assert adapter.start(state, {}).status is SkillStatus.RUNNING
    assert adapter.tick(state, {}, 2.0).status is SkillStatus.SUCCESS
    assert calls == [("start", state.runtime_id), ("tick", 2.0)]
    assert adapter.snapshot(state)["runtime_id"] == state.runtime_id


def test_skill_adapter_cancel_is_typed_and_does_not_finalize_runtime():
    adapter = SkillContractAdapter(
        lambda state, world: SkillResult(SkillStatus.RUNNING),
        lambda state, world, now: SkillResult(SkillStatus.RUNNING))
    state = _state()
    result = adapter.cancel(state, FailureReason.INTERRUPTED)
    assert result.status is SkillStatus.CANCELLED
    assert result.reason is FailureReason.INTERRUPTED
    assert state.status is SkillStatus.RUNNING
