"""V4-051 wiring: terminal credit feeds belief and Planner consumes it."""
import inspect

from wowbot.agent.collect_strategy import CollectStrategy
from wowbot.agent.models import Attempt, Observation, Outcome, Prediction, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.quest_terminal import QuestTerminalProcessor
from wowbot.agent.world import WorldModel
from wowbot.runtime import VerificationResult


class _StubVerifier:
    def __init__(self, success: bool):
        self.success = success

    def evaluate(self, before, after, *, quest_ids, objective_ids):
        return VerificationResult(self.success, .9 if self.success else .1, None, ("stub",))


class _StubQuestRuntime:
    def record_success(self, **kwargs):
        pass

    def record_failure(self, **kwargs):
        return None


def _attempt(skill: str, quest_id=10, objective_id="0"):
    params = {"quest_ids": [quest_id], "objective_ids": [objective_id]}
    return Attempt("action", Proposal.make(skill, "test", params), {}, "obs", 1., 5., (),
                   Prediction("prediction", "action", "state", 1., 5., "obs"))


def test_successful_loot_with_credit_strengthens_mob_loot_belief():
    domain = QuestDomain()
    processor = QuestTerminalProcessor(_StubVerifier(True), _StubQuestRuntime(), domain)
    processor.process(_attempt("LOOT"), Outcome.SUCCESS, "", {}, None, 1.0)
    assert domain.collect_strategy.best_guess(10, "0") is CollectStrategy.MOB_LOOT
    assert domain.collect_strategy.confidence_of(10, "0", CollectStrategy.MOB_LOOT) > 0.0


def test_successful_loot_without_credit_weakens_mob_loot_belief():
    domain = QuestDomain()
    processor = QuestTerminalProcessor(_StubVerifier(True), _StubQuestRuntime(), domain)
    domain.collect_strategy.record_outcome(10, "0", strategy=CollectStrategy.MOB_LOOT, objective_progressed=True)
    before = domain.collect_strategy.confidence_of(10, "0", CollectStrategy.MOB_LOOT)

    processor2 = QuestTerminalProcessor(_StubVerifier(False), _StubQuestRuntime(), domain)
    processor2.process(_attempt("LOOT"), Outcome.SUCCESS, "", {}, None, 2.0)
    after = domain.collect_strategy.confidence_of(10, "0", CollectStrategy.MOB_LOOT)
    assert after < before


def test_object_use_strengthens_ground_object_belief():
    domain = QuestDomain()
    processor = QuestTerminalProcessor(_StubVerifier(True), _StubQuestRuntime(), domain)
    processor.process(_attempt("OBJECT_USE"), Outcome.SUCCESS, "", {}, None, 1.0)
    assert domain.collect_strategy.best_guess(10, "0") is CollectStrategy.GROUND_OBJECT


def test_combat_never_feeds_the_collect_strategy_belief():
    domain = QuestDomain()
    processor = QuestTerminalProcessor(_StubVerifier(True), _StubQuestRuntime(), domain)
    processor.process(_attempt("COMBAT"), Outcome.SUCCESS, "", {}, None, 1.0)
    assert domain.collect_strategy.best_guess(10, "0") is CollectStrategy.UNKNOWN


def _collect_world() -> WorldModel:
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "test:player", "timestamp": 1., "frame_id": "f1",
        "player_present": True, "active_quests": [{
            "quest_id": 10, "title": "Collect", "is_complete": False,
            "objectives": [{"objective_id": "0", "type": "COLLECT",
                            "description": "Collect 3 kits", "current": 0,
                            "required": 3, "is_complete": False}],
        }],
    }, 1.))
    return world


def test_unknown_collect_belief_does_not_change_existing_proposals():
    domain = QuestDomain()
    original = Proposal.make("OBJECT_USE", "candidate", {
        "objective_id": "0", "quest_ids": [10]}, priority=50)
    assert domain.apply_collect_strategy([original], _collect_world()) == [original]


def test_credit_learned_collect_source_guides_but_does_not_suppress_alternatives():
    domain = QuestDomain()
    domain.collect_strategy.record_outcome(
        10, "0", strategy=CollectStrategy.GROUND_OBJECT,
        objective_progressed=True)
    object_use = Proposal.make("OBJECT_USE", "object", {
        "objective_id": "0", "quest_ids": [10]}, priority=50)
    combat = Proposal.make("COMBAT", "mob", {
        "objective_ids": ["0"], "quest_ids": [10]}, priority=50)

    guided = domain.apply_collect_strategy([object_use, combat], _collect_world())

    assert len(guided) == 2
    assert guided[0].priority > object_use.priority
    assert guided[0].parameters["collect_strategy_guidance"]["strategy"] == "GROUND_OBJECT"
    assert guided[1] == combat


def test_planner_applies_collect_guidance_before_global_ranking():
    source = inspect.getsource(Planner.candidates)
    assert source.index("apply_collect_strategy") < source.index("proposal_ranker.rank")
