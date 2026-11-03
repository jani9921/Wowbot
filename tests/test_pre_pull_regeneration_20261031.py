"""REV4 survival supplement (2026-10-30): regenerate before a new pull.

Hysteretic thresholds, own health from fresh field evidence only (UNKNOWN is
never 100 %), defence/loot/talk untouched, no rest/pull loop when no
regeneration is observed, and an interruption is a preemption."""
from wowbot.agent.models import Attempt, Goal, Observation, Prediction, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.skill_contracts import CONTRACTS
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.survival_planning import (REST_END_FRACTION, REST_START_FRACTION, ReadinessPolicy,
                                            own_health_fraction)
from wowbot.agent.world import WorldModel
from wowbot.runtime import ActiveSkillRuntime, FailureReason, Intent, SkillStatus
from wowbot.runtime.m0_dispatch import M0SkillDispatcher
from wowbot.runtime.verification_engine import VerificationEngine
from wowbot.skills.rest import RestSkill

PACKET = {"selected_fields": {"health": {}, "max_health": {}}}


def health(value, maximum=1000., **extra):
    return {"health": value, "max_health": maximum, "packet_own_health": PACKET,
            "monotonic_time": 10., "is_in_combat": False, **extra}


def pull():
    return Proposal.make("MOVE", "kill target", {"purpose": "APPROACH_SERVER_KILL_TARGET", "x": 1., "y": 2.},
                         priority=96)


def talk():
    return Proposal.make("SOFT_INTERACT", "talk", {"soft_guid": "Creature-0-1-2-3-4-5"}, priority=103)


def test_own_health_is_fresh_field_evidence_or_unknown():
    assert own_health_fraction(health(400.)) == .4
    assert own_health_fraction({"health": 400., "max_health": 1000.}) is None          # no sample: UNKNOWN
    assert own_health_fraction({"health": 400., "max_health": 1000., "health_sample_time": 9.5,
                                "monotonic_time": 10.}) == .4
    assert own_health_fraction({"health": 400., "max_health": 1000., "health_sample_time": 7.,
                                "monotonic_time": 10.}) is None
    assert own_health_fraction(health(None)) is None and own_health_fraction(health(1., 0.)) is None


def test_hysteresis_rests_below_the_start_and_until_the_finish_threshold():
    policy = ReadinessPolicy()
    assert policy.assess(health(600.), 10.)["state"] == "READY"            # enough: no needless rest
    assert policy.assess(health(400.), 11.)["state"] == "REST"
    assert policy.assess(health(700.), 12.)["state"] == "REST"             # still below the finish
    assert policy.assess(health(REST_END_FRACTION*1000.), 13.)["state"] == "READY"
    assert policy.assess(health(700.), 14.)["state"] == "READY"            # above the start again
    assert REST_START_FRACTION < REST_END_FRACTION


def test_a_rest_withholds_new_pulls_only_and_never_a_defence():
    policy = ReadinessPolicy()
    kept = policy.apply([pull(), talk()], health(300.), 10.)
    assert [p.skill for p in kept] == ["SOFT_INTERACT", "REST"]
    rest = kept[-1]
    assert rest.parameters["purpose"] == "PRE_PULL_REGENERATION" and rest.priority > talk().priority
    attacked = policy.apply([pull()], health(300., is_in_combat=True), 11.)
    assert [p.skill for p in attacked] == ["MOVE"]                         # combat owns the attacked character
    assert [p.skill for p in policy.apply([pull()], health(900.), 12.)] == ["MOVE"]


def test_unknown_health_after_a_low_reading_keeps_resting_but_unknown_alone_does_not():
    policy = ReadinessPolicy()
    assert [p.skill for p in policy.apply([pull()], {"monotonic_time": 10.}, 10.)] == ["MOVE"]
    policy.apply([pull()], health(300.), 11.)
    rest = policy.apply([pull()], {"monotonic_time": 12.}, 12.)
    assert [p.skill for p in rest] == ["REST"]
    assert rest[0].parameters["reason"] == "unknown_after_low_health"


def test_no_observed_regeneration_does_not_loop_rest_and_pull():
    policy = ReadinessPolicy()
    policy.apply([pull()], health(300.), 10.)
    failed = {"action_id": "a1", "skill": "REST", "outcome": "FAILURE", "reason": "no_health_regeneration"}
    assert [p.skill for p in policy.apply([pull()], health(300.), 21., failed)] == ["MOVE"]
    assert [p.skill for p in policy.apply([pull()], health(300.), 40., failed)] == ["MOVE"]   # noted once
    assert [p.skill for p in policy.apply([pull()], health(300.), 52.)] == ["REST"]           # bounded retry


def test_an_escort_in_view_is_not_left_behind_to_rest(monkeypatch):
    import wowbot.agent.survival_planning as survival
    monkeypatch.setattr(survival, "escort_active", lambda state: True)
    assert [p.skill for p in ReadinessPolicy().apply([pull()], health(300.), 10.)] == ["MOVE"]


def _rest_state(now=10., deadline=55.):
    proposal = Proposal.make("REST", "rest", {"end_fraction": .9})
    attempt = Attempt("a", proposal, {}, "o", now, deadline, (), Prediction("p", "a", "x", now, deadline, "o"))
    runtime = ActiveSkillRuntime()
    runtime.start(intent=Intent("REST", proposal.parameters), attempt=attempt, now=now)
    return runtime.state


def test_rest_succeeds_on_observed_health_and_issues_no_input():
    skill, state = RestSkill(), _rest_state()
    started = skill.begin(state, health(300.), 10.)
    assert started.status is SkillStatus.RUNNING and not started.commands
    assert skill.verify(state, health(500.), 12.).status is SkillStatus.RUNNING
    done = skill.verify(state, health(910.), 14.)
    assert done.status is SkillStatus.SUCCESS and "own_health_regenerated" in done.evidence


def test_rest_ends_without_regeneration_and_yields_to_a_threat():
    skill, state = RestSkill(), _rest_state()
    skill.begin(state, health(300.), 10.)
    assert skill.verify(state, health(300.), 15.).status is SkillStatus.RUNNING
    stalled = skill.verify(state, health(300.), 20.5)
    assert stalled.status is SkillStatus.FAILURE and stalled.reason is FailureReason.NO_PROGRESS
    assert stalled.metadata["reason"] == "no_health_regeneration"
    other = _rest_state()
    skill.begin(other, health(300.), 10.)
    threat = skill.verify(other, health(300., is_in_combat=True), 11.)
    assert threat.status is SkillStatus.CANCELLED and threat.reason is FailureReason.INTERRUPTED
    assert skill.verify(other, health(300., is_dead=True), 11.).reason is FailureReason.PLAYER_DEAD


def test_rest_goes_through_the_canonical_skill_boundary():
    assert M0SkillDispatcher.handles("REST")
    assert any(contract.name == "REST" for contract in CONTRACTS)
    decision = VerificationEngine().confirm("REST", RestSkill().verify(_rest_state(), health(950.), 11.))
    assert decision.reason == "own_health_regenerated_verified"


def test_the_planner_rests_instead_of_pulling_with_low_server_health():
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "test:player", "timestamp": 1., "frame_id": "f1", "map_id": 1409,
        "world_map_open": False, "position": {"x": .5, "y": .5}, "orientation": 0.,
        "player_present": True, "is_in_combat": False, "is_casting": False, "target": {},
        "active_quests": []}, 1.))
    world.state.update(health(300.), monotonic_time=1., runtime_profile="SERVER")
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1.), world, 1.)
    assert any(p.skill == "REST" for p in proposals)
    assert not any(p.parameters.get("purpose") == "APPROACH_SERVER_KILL_TARGET" for p in proposals)
