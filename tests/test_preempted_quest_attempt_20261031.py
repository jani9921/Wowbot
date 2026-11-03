"""Live 2026-10-28 15:40:05 (65793 "Escort the Wagon"): a hostile interrupted
the stationary hold beside the wagon (WAIT_EVENT, reason "interrupted").  The
quest failure memory suppressed that WAIT_EVENT for 15 s, the escort policy
had no hold proposal left, the POI-search MOVE won and the agent flew to the
quest-area centre.  A preemption is not a failed approach."""
from types import SimpleNamespace

from wowbot.agent.models import Attempt, Goal, Outcome, Prediction, Proposal
from wowbot.agent.quest_failure_memory import QuestFailureMemory
from wowbot.agent.quest_terminal import QuestTerminalProcessor
from wowbot.runtime import FailureReason


def test_a_preempted_attempt_is_not_suppressed():
    memory = QuestFailureMemory()
    for reason in ("interrupted", "INTERRUPTED", "cancelled", FailureReason.INTERRUPTED.value.lower()):
        assert memory.record(quest_id="65793", objective_id="65793:2", target_ref=None,
                             skill="WAIT_EVENT", reason=reason, now=1.) is None
    assert memory.permits(quest_id="65793", objective_id="65793:2", target_ref=None,
                          skill="WAIT_EVENT", now=1.1)
    assert memory.record(quest_id="65793", objective_id="65793:2", target_ref=None,
                         skill="WAIT_EVENT", reason="timeout", now=1.) is not None   # a real failure still is


def test_the_terminal_processor_records_no_failure_for_an_interrupted_wait():
    memory = QuestFailureMemory()
    runtime = SimpleNamespace(record_failure=lambda **kw: memory.record(
        quest_id=kw["parameters"]["quest_id"], objective_id=kw["parameters"]["objective_id"],
        target_ref=None, skill=kw["skill"], reason=kw["reason"], now=kw["now"]))
    verifier = SimpleNamespace(evaluate=lambda *a, **k: SimpleNamespace(success=False, evidence=()))
    domain = SimpleNamespace(attempt_memory=SimpleNamespace(), collect_strategy=None)
    processor = QuestTerminalProcessor(verifier, runtime, domain)
    proposal = Proposal.make("WAIT_EVENT", "hold beside the wagon",
                             {"quest_id": "65793", "objective_id": "65793:2", "objective_kind": "ESCORT"})
    attempt = Attempt("a", proposal, {}, "o", 1., 9., (), Prediction("p", "a", "x", 1., 9., "o"))
    original = {}
    for name in ("gossip_trials", "quest_playbooks"):
        module = __import__(f"wowbot.agent.{name}", fromlist=["record_trial"])
        original[name] = module.record_trial
        module.record_trial = lambda *a, **k: None
    try:
        result = processor.process(attempt, Outcome.FAILURE, "interrupted", {}, Goal.parse("Questelj", 1.), 2.)
    finally:
        for name, function in original.items():
            __import__(f"wowbot.agent.{name}", fromlist=["record_trial"]).record_trial = function
    assert not [kind for kind, _ in result.events if kind == "QUEST_FAILURE_RECORDED"]
