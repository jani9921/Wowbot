"""Live 2026-11-02 (Jangolode): the agent walked between two quests' areas
seven times.  While the quest whose work area we stand in still proposes
something (within 25 s), a far MOVE for another quest yields; when the local
quest has nothing for longer, leaving is allowed again."""
from types import SimpleNamespace

from test_quest_agenda import goal, world
from wowbot.agent.models import Proposal
from wowbot.agent.quest_agenda import QuestAgenda

REGISTRY = SimpleNamespace(available=lambda proposal, model: True)


def move(qid, x, priority=57.):
    return Proposal.make("MOVE", "area", {"quest_id": qid, "x": x, "y": 0., "instance_id": 2175,
                                          "coordinate_space": "WORLD_YARDS"}, priority=priority)


def test_a_far_move_for_another_quest_yields_while_the_local_quest_works():
    agenda, model = QuestAgenda(), world(x=110.)                 # quest 1's work area is at x=110
    agenda.refresh(goal(), model, 10.)
    local = Proposal.make("OBJECT_USE", "use", {"quest_ids": [1]}, priority=50.)
    ranked = {p.parameters.get("quest_id"): p.priority
              for p in agenda.apply([local, move(2, 400.)], model, 10., registry=REGISTRY, blocked_until={})
              if p.skill == "MOVE"}
    assert ranked[2] == 57.-QuestAgenda.LEAVE_PENALTY
    # The local quest proposed nothing for longer than the grace: leaving is fine.
    later = agenda.apply([move(2, 400.)], model, 10.+QuestAgenda.LOCAL_GRACE_SECONDS+1., registry=REGISTRY,
                         blocked_until={})
    assert later[0].priority >= 57.


def test_a_near_move_for_another_quest_is_not_penalized():
    agenda, model = QuestAgenda(), world(x=110.)
    agenda.refresh(goal(), model, 10.)
    local = Proposal.make("OBJECT_USE", "use", {"quest_ids": [1]}, priority=50.)
    near = [p for p in agenda.apply([local, move(2, 150.)], model, 10., registry=REGISTRY, blocked_until={})
            if p.skill == "MOVE"]
    assert near[0].priority >= 57.
