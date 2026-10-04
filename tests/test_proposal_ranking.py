from types import SimpleNamespace

from wowbot.agent.models import Goal, Proposal
from wowbot.agent.proposal_ranking import ProposalRanker


class World:
    state = {"game_build": "12.1", "map_id": 1409}

    @staticmethod
    def distance(parameters):
        return parameters.get("distance")


class Registry:
    contracts = {"MOVE": SimpleNamespace(cost=1.),
                 "TALK": SimpleNamespace(cost=.2)}

    @staticmethod
    def available(proposal, world):
        return proposal.parameters.get("available", True)


def _rank(proposals, **overrides):
    return ProposalRanker.rank(
        proposals, goal=Goal.parse("Questelj", 1), world=World(), now=5.,
        registry=Registry(), memory=None, blocked_until={}, recent={},
        evidence=("obs-1",), **overrides)


def test_ranking_filters_blocked_recent_unavailable_and_already_arrived_moves():
    blocked = Proposal.make("TALK", "blocked", {"guid": "blocked"})
    recent = Proposal.make("INSPECT", "recent")
    unavailable = Proposal.make("TALK", "unavailable", {"available": False})
    arrived = Proposal.make("MOVE", "arrived", {"distance": .002})
    usable = Proposal.make("TALK", "usable", {"guid": "usable"}, priority=10)

    result = ProposalRanker.rank(
        [blocked, recent, unavailable, arrived, usable],
        goal=Goal.parse("Questelj", 1), world=World(), now=5.,
        registry=Registry(), memory=None,
        blocked_until={blocked.key: 6.}, recent={recent.key: 6.},
        evidence=("obs-1",))

    assert [proposal.reason for proposal in result.proposals] == ["usable"]
    assert result.proposals[0].evidence == ("obs-1",)
    assert result.scores[result.proposals[0].key]["total"] > 0


def test_ranking_returns_evidence_bound_wait_when_no_proposal_is_actionable():
    result = _rank([Proposal.make("TALK", "no", {"available": False})])
    assert len(result.proposals) == 1
    assert result.proposals[0].skill == "WAIT"
    assert result.proposals[0].evidence == ("obs-1",)
    assert result.pattern_analysis["mode"] == "NO_REFERENCE"


def test_wait_explains_unavailable_combat_capability():
    result = _rank([Proposal.make("COMBAT", "target", {"available": False})])
    wait = result.proposals[0]
    assert wait.skill == "WAIT"
    assert wait.parameters["waiting_for"] == ["USABLE_COMBAT_ACTION_OR_RESOURCE"]
    assert wait.parameters["unavailable_skills"] == ["COMBAT"]
    assert "használható action" in wait.reason
