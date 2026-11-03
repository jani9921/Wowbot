"""REV4 P8.3: the order of several ready/active quests lives in QuestAgenda.

* An objective the P8.1 probe ladder exhausted is set aside (bounded): the
  quest's WORK step is DEFERRED_EXHAUSTED and its search/approach/wait yield
  to any other ready task; alone, it keeps them.  Progress or the deferral's
  end gives the ladder a fresh round.
* The turn-in zone rule (user 2026-10-31: "do not go to another map and come
  back") ranks every ready task: another zone comes after the same/unknown."""
from types import SimpleNamespace

from test_quest_agenda import by_key, goal, quest, world
from wowbot.agent.models import Proposal
from wowbot.agent.objective_probes import ObjectiveProbeLadder
from wowbot.agent.quest_agenda import QuestAgenda

REGISTRY = SimpleNamespace(available=lambda proposal, model: True)


class Zones:
    def zone(self, ui_map):
        return {1409: 1409, 52: 52}.get(ui_map)

    def _client(self):
        raise LookupError("no catalog in tests")


def move(qid, **extra):
    return Proposal.make("MOVE", "work", {"quest_id": qid, "x": 1., "y": 0., **extra}, priority=50.)


def test_an_exhausted_objective_is_set_aside_while_other_work_is_ready():
    agenda, model = QuestAgenda(), world()
    agenda.exhausted_objectives = frozenset({("1", "1:0")})
    agenda.refresh(goal(), model, 10.)
    steps = by_key(agenda)
    assert steps["work:1"]["status"] == "DEFERRED_EXHAUSTED"
    assert steps["work:1"]["deferred_reason"] == "objective_probes_exhausted"
    assert agenda.preferred_key == "work:2"
    ranked = {p.parameters["quest_id"]: p.priority for p in agenda.apply(
        [move(1), move(2), Proposal.make("WAIT", "probes", {"quest_id": 1, "reason": "objective_probes_exhausted"},
                                         priority=59.)], model, 10., registry=REGISTRY, blocked_until={})
              if p.skill == "MOVE"}
    assert ranked[1] == 30. and ranked[2] == 62.


def test_a_lone_exhausted_quest_keeps_its_proposals():
    agenda, model = QuestAgenda(), world([quest(1)])
    agenda.exhausted_objectives = frozenset({("1", "1:0")})
    agenda.refresh(goal(), model, 10.)
    (only,) = agenda.apply([move(1)], model, 10., registry=REGISTRY, blocked_until={})
    assert only.priority == 50.


def test_another_zones_turnin_comes_after_the_local_one_even_when_nearer():
    model = world([quest(1, True), quest(2, True)], x=-180.)
    plain = QuestAgenda()
    plain.zones = Zones()
    plain.refresh(goal(), model, 10.)
    assert plain.preferred_key == "turnin:1"                       # nearest ender
    model.state["packet_quest_pois"] = {"1": {"blobs": [{"objective_index": -1, "objective_id": 0,
                                                         "ui_map_id": 52}]}}
    zoned = QuestAgenda()
    zoned.zones = Zones()
    zoned.refresh(goal(), model, 10.)
    assert zoned.preferred_key == "turnin:2"                       # quest 1 is handed in in Westfall


class Objective(SimpleNamespace):
    pass


def test_the_ladder_deferral_is_bounded_and_progress_ends_it():
    ladder = ObjectiveProbeLadder()
    ladder.exhausted[("1", "1:0")] = 10.
    ladder.talked["1"] = {"npc": 9.}
    assert ladder.deferred(100.) == {("1", "1:0")}
    assert ladder.deferred(10.+ObjectiveProbeLadder.DEFER_SECONDS) == frozenset()
    assert "1" not in ladder.talked                                # one fresh round
    ladder.exhausted[("1", "1:0")] = 20.
    ladder._observe_progress(("1", "1:0"), Objective(current_count=0, completion_state="ACTIVE"))
    ladder._observe_progress(("1", "1:0"), Objective(current_count=1, completion_state="ACTIVE"))
    assert ladder.deferred(21.) == frozenset()
