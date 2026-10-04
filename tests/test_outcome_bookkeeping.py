from types import SimpleNamespace

from wowbot.agent.models import Outcome, Proposal
from wowbot.agent.outcome_bookkeeping import AttemptOutcomeBookkeeper


class FailureManager:
    def __init__(self): self.successes = []
    def record_success(self, key): self.successes.append(key)


class LoopGuard:
    def __init__(self): self.cleared = []
    def clear_prefix(self, prefix): self.cleared.append(prefix)


class Query:
    def __init__(self, target=None): self._target = target
    def target(self): return self._target


class World:
    def __init__(self, target=None):
        self.query = Query(target)
        self.latest = SimpleNamespace(observation_id="obs:2")
        self.looted = []
        self.killed = []
    def mark_corpse_looted(self, guid, now): self.looted.append((guid, now))
    def mark_combat_kill(self, guid, now): self.killed.append((guid, now))


def setup(target=None):
    return (
        SimpleNamespace(completed_steps=0, failures=0), World(target),
        SimpleNamespace(blocked_until={}, quest=SimpleNamespace(
            interaction_range_blocks={})), {}, FailureManager(), LoopGuard(),
        SimpleNamespace(max_backoff_seconds=30.),
    )


def attempt(skill, parameters=None):
    proposal = Proposal.make(skill, "test", parameters)
    return SimpleNamespace(proposal=proposal)


def apply(value, outcome, reason, now=10., target=None, failure_decision=None):
    goal, world, planner, failures, manager, loop, retries = setup(target)
    AttemptOutcomeBookkeeper.apply(
        value, outcome, reason, now, goal=goal, world=world,
        planner=planner, failures=failures, failure_manager=manager,
        loop_guard=loop, retries=retries,
        failure_decision=failure_decision)
    return goal, world, planner, failures, manager, loop


def test_success_updates_goal_clears_failure_chain_and_records_own_kill():
    value = attempt("COMBAT", {"guid": "Creature-42"})
    goal, world, _, failures, manager, loop = apply(
        value, Outcome.SUCCESS, "target_death_verified")

    assert goal.completed_steps == 1
    assert failures[value.proposal.key] == 0
    assert manager.successes == [value.proposal.key]
    assert loop.cleared == [f"COMBAT:Creature-42:"]
    assert world.killed == [("Creature-42", 10.)]


def test_loot_success_records_corpse_and_bounded_cooldown():
    value = attempt("LOOT", {"guid": "Creature-42"})
    _, world, planner, _, _, _ = apply(
        value, Outcome.SUCCESS, "loot_received", now=20.)

    assert world.looted == [("Creature-42", 20.)]
    assert planner.blocked_until[value.proposal.key] == 80.


def test_matching_unobserved_interaction_becomes_candidate_range_evidence():
    value = attempt("INTERACT", {"guid": "Creature-42"})
    goal, _, planner, failures, _, _ = apply(
        value, Outcome.FAILURE, "expected_observation_missing",
        target={"guid": "Creature-42"})

    evidence = planner.quest.interaction_range_blocks["Creature-42"]
    assert goal.failures == 1 and failures[value.proposal.key] == 1
    assert evidence["belief"] == "CANDIDATE"
    assert evidence["observation_id"] == "obs:2"
    assert value.proposal.key not in planner.blocked_until


def test_ordinary_failure_uses_failure_manager_backoff():
    value = attempt("COMBAT", {"guid": "Creature-42"})
    decision = SimpleNamespace(retry_allowed=True, backoff_seconds=7.)
    goal, _, planner, failures, _, _ = apply(
        value, Outcome.FAILURE, "spell_not_ready",
        failure_decision=decision)

    assert goal.failures == 1 and failures[value.proposal.key] == 1
    assert planner.blocked_until[value.proposal.key] == 17.


def test_far_silent_interact_becomes_candidate_range_evidence_until_range_is_verified():
    """Retail exports no NPC distance and far INTERACTTARGET is often silent."""
    value = attempt("INTERACT", {"guid": "Creature-42"})
    _, _, planner, _, _, _ = apply(
        value, Outcome.FAILURE, "no_response", target={"guid": "Creature-42"})
    assert planner.quest.interaction_range_blocks["Creature-42"]["belief"] == "CANDIDATE"


def test_client_range_error_raises_the_units_visual_interaction_height():
    from wowbot.agent.quest_planning import QuestDomain
    quest = QuestDomain.__new__(QuestDomain)
    quest.approach_verified_at = {"Creature-42": 1.}
    quest.interaction_ready_height = {}
    state = {"target": {"guid": "Creature-42", "visual_track_id": "WORLD3D:7"},
             "visual_candidates": [{"track_id": "WORLD3D:7", "lifecycle": "ACTIVE",
                                    "bbox_height_fraction": .15}]}
    quest.learn_out_of_range(state, "Creature-42")
    assert "Creature-42" not in quest.approach_verified_at
    # max(default .19 * 1.25, measured .15 * 1.3): at least +25 % per error.
    assert abs(quest.ready_height("Creature-42") - .2375) < 1e-9
    assert not quest._target_visually_in_range(state, "Creature-42")
