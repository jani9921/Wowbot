from __future__ import annotations

from dataclasses import dataclass, field

from wowbot.agent.decision_fingerprint import (
    DecisionFingerprint,
    DecisionFingerprintGuard,
    evidence_signature,
)
from wowbot.agent.models import Goal, Proposal
from wowbot.agent.planner import Planner
from wowbot.runtime.contracts import FailureReason


def goal() -> Goal:
    return Goal("goal-1", "Questelj", "QUEST", 0.)


def proposal(**changes) -> Proposal:
    params = {
        "guid": "Creature-1",
        "objective_id": "obj-1",
        "purpose": "QUEST_INTERACTION",
        **changes,
    }
    return Proposal.make("INTERACT", "test", params)


def state(**changes) -> dict:
    value = {
        "session_id": "session-1",
        "map_id": 1409,
        "position": {"x": 10., "y": 20.},
        "quest_state_revision": 2,
        "target": {"guid": "Creature-1", "is_dead": False},
        "active_quests": [{
            "quest_id": 1,
            "objectives": [{"objective_id": "obj-1", "current": 0, "required": 1}],
        }],
        **changes,
    }
    return value


def test_fingerprint_is_decision_target_strategy_not_reason_or_visual_jitter():
    first = DecisionFingerprint.from_proposal(proposal(x=.1), goal())
    second = DecisionFingerprint.from_proposal(proposal(x=.1008), goal())
    assert first == second
    assert first.decision == "INTERACT"
    assert first.target == "guid=Creature-1"
    assert first.strategy == "purpose=QUEST_INTERACTION"


def test_nonretryable_decision_stays_blocked_across_frame_timestamp_churn():
    guard = DecisionFingerprintGuard()
    candidate = proposal()
    before = state(frame_id="f1", timestamp=1.)
    guard.record_nonretryable(candidate, goal(), before,
                              reason=FailureReason.NO_RESPONSE, now=1.)
    assert guard.permits(candidate, goal(), state(frame_id="f99", timestamp=999.)) is False


def test_meaningful_new_evidence_releases_the_exact_decision():
    guard = DecisionFingerprintGuard()
    candidate = proposal()
    guard.record_nonretryable(candidate, goal(), state(), reason="NO_RESPONSE", now=1.)
    changed = state(
        quest_state_revision=3,
        active_quests=[{
            "quest_id": 1,
            "objectives": [{"objective_id": "obj-1", "current": 1, "required": 1}],
        }],
    )
    assert guard.permits(candidate, goal(), changed) is True
    assert guard.snapshot() == ()


def test_a_different_target_or_strategy_is_not_suppressed():
    guard = DecisionFingerprintGuard()
    guard.record_nonretryable(proposal(), goal(), state(), reason="NO_RESPONSE", now=1.)
    assert guard.permits(proposal(guid="Creature-2"), goal(), state()) is True
    assert guard.permits(proposal(purpose="QUEST_TURN_IN"), goal(), state()) is True


@dataclass
class Record:
    reason: FailureReason = FailureReason.NO_RESPONSE


@dataclass
class Decision:
    retry_allowed: bool
    record: Record = field(default_factory=Record)


class World:
    def __init__(self, value):
        self.state = value


def test_planner_production_filter_activates_only_after_retry_budget_exhaustion():
    planner = Planner(registry=object())
    candidate = proposal()
    current_goal = goal()
    world = World(state())
    planner.record_terminal_decision(
        candidate, current_goal, world, Decision(retry_allowed=True),
        success=False, now=1.)
    assert planner.filter_decision_loops([candidate], current_goal, world.state) == [candidate]
    planner.record_terminal_decision(
        candidate, current_goal, world, Decision(retry_allowed=False),
        success=False, now=2.)
    assert planner.filter_decision_loops([candidate], current_goal, world.state) == []


def test_evidence_signature_excludes_transport_noise_but_tracks_position():
    first = evidence_signature(state(frame_id="one", timestamp=1.))
    assert first == evidence_signature(state(frame_id="two", timestamp=2.))
    assert first != evidence_signature(state(position={"x": 11., "y": 20.}))
