from wowbot.agent.models import Proposal
from wowbot.agent.passive_wait import PassiveWaitBudget
from test_agent_core import agent, state


def test_different_wait_reasons_share_one_five_second_budget():
    budget = PassiveWaitBudget(5.)
    first = budget.observe(
        Proposal.make("WAIT", "route blocked", {"waiting_for": ["ROUTE"]}),
        observation_id="o1", now=10.)
    second = budget.observe(
        Proposal.make("WAIT", "unresolved", {"waiting_for": ["EVIDENCE"]}),
        observation_id="o2", now=13.)
    expired = budget.observe(
        Proposal.make("WAIT", "commitment waiting"),
        observation_id="o3", now=15.)

    assert not first.expired and not second.expired
    assert expired.expired and expired.first_expiration
    assert expired.proposal.parameters["passive_wait_started_at"] == 10.
    assert expired.proposal.parameters["passive_wait_deadline"] == 15.
    assert expired.proposal.parameters["next_action"] == "FORCED_REPLAN"
    assert expired.fresh_observations == 3


def test_wait_expiration_is_reported_once_until_real_action_resets_it():
    budget = PassiveWaitBudget(5.)
    budget.observe(Proposal.make("WAIT", "one"), observation_id="o1", now=1.)
    first = budget.observe(Proposal.make("WAIT", "two"), observation_id="o2", now=6.)
    repeated = budget.observe(Proposal.make("WAIT", "three"), observation_id="o3", now=7.)
    assert first.first_expiration
    assert repeated.expired and not repeated.first_expiration

    budget.reset("non_wait_skill_started")
    fresh = budget.observe(Proposal.make("WAIT", "later"), observation_id="o4", now=20.)
    assert fresh.proposal.parameters["passive_wait_started_at"] == 20.
    assert not fresh.expired


def test_wait_diagnostics_preserve_specific_wakeup_contract():
    budget = PassiveWaitBudget(5.)
    decision = budget.observe(Proposal.make(
        "WAIT", "route blocked",
        {"waiting_for": ["ALTERNATIVE_ROUTE"], "retry_at": 6.,
         "next_action": "REPLAN_ALTERNATIVE_OR_RETRY"}),
        observation_id="o1", now=1.)

    parameters = decision.proposal.parameters
    assert parameters["waiting_for"] == ["ALTERNATIVE_ROUTE"]
    assert parameters["retry_at"] == 6.
    assert parameters["next_action"] == "REPLAN_ALTERNATIVE_OR_RETRY"


def test_runtime_exposes_expired_shared_wait_budget_and_forces_replan():
    bot, executor = agent()
    bot.planner.candidates = lambda goal, world, now: [
        Proposal.make("WAIT", "still unresolved",
                      {"waiting_for": ["QUEST_EVIDENCE"]})]

    first = bot.tick(state(1.), 1.)
    expired = bot.tick(state(6.), 6.)

    assert first["decision"]["parameters"]["passive_wait_expired"] is False
    assert expired["decision"]["parameters"]["passive_wait_expired"] is True
    assert expired["decision"]["parameters"]["passive_wait_started_at"] == 1.
    assert expired["decision"]["parameters"]["next_action"] == "FORCED_REPLAN"
    assert expired["autonomous_loop"]["last_replan_trigger"] == "PASSIVE_WAIT_BUDGET_EXHAUSTED"
    assert not executor.commands
