"""Deterministic M0 replay smoke coverage (100 bounded iterations)."""
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillResult, SkillStatus


class Attempt:
    deadline = 2.0


def test_active_skill_runtime_never_admits_a_second_action_across_100_replays():
    for index in range(100):
        runtime = ActiveSkillRuntime()
        runtime.start(intent=Intent("REPLAY", {"iteration": index}), attempt=Attempt(), now=0.)
        try:
            runtime.start(intent=Intent("SECOND"), attempt=Attempt(), now=.1)
        except RuntimeError:
            pass
        else:
            raise AssertionError("a second active skill was admitted")
        runtime.finish(SkillResult(SkillStatus.SUCCESS), 1.)
        assert runtime.state is not None and runtime.state.status is SkillStatus.SUCCESS
        runtime.finalize()
        assert runtime.state is None
