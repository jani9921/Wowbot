from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.models import Goal, Observation, Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.quest_semantics import use_on_subjects
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel


class _SelectedBindings:
    """Minimal selected-cache double: no implicit key fallback is allowed."""

    def __init__(self, actions=("ACTIONBUTTON1",)):
        self.actions = set(actions)

    def contains(self, action):
        return action in self.actions


def world(**extra):
    value = WorldModel()
    value.ingest(Observation.create({"session_id": "s", "frame_id": "f", "timestamp": 1,
        "map_id": 1409, "position": {"x": .5, "y": .5}, "orientation": 0,
        "player_present": True, "world_map_open": False, **extra}, 1))
    return value


BJORN_TARGET = {"guid": "Creature-1", "name": "Bjorn Stouthands", "attackable": False, "dead": False,
                "health": 40, "max_health": 100}
FIRST_AID_KIT_ACTION = {"action": "ACTIONBUTTON1", "kind": "item", "name": "First Aid Kit", "id": 175241,
                        "is_usable": True, "is_harmful": False, "cooldown_remaining": 0}
QUEST = {"quest_id": 1, "title": "Emergency First Aid", "objectives": [
    {"type": "object", "description": "Use a First Aid Kit on Bjorn Stouthands, Kee-la, and Austin Huxworth",
     "required": 3, "current": 0, "target_object": {"item_id": 175241}}]}


# --- quest_semantics.use_on_subjects ---------------------------------------

def test_use_on_subjects_extracts_named_list():
    subjects = use_on_subjects({"description": "Use a First Aid Kit on Bjorn Stouthands, Kee-la, and Austin Huxworth"})
    assert subjects == ["bjorn stouthands", "kee-la", "austin huxworth"]


def test_use_on_subjects_empty_when_no_on_clause():
    assert use_on_subjects({"description": "Collect 5 Linen Cloth"}) == []


def test_use_on_subjects_empty_when_complete():
    assert use_on_subjects({"description": "Use a Kit on Bo", "is_complete": True}) == []


# --- SkillRegistry.beneficial_action / available ----------------------------

def test_beneficial_action_finds_matching_item_slot():
    registry = SkillRegistry()
    action = registry.beneficial_action({"actionbar": [FIRST_AID_KIT_ACTION]}, 175241)
    assert action is not None and action["action"] == "ACTIONBUTTON1"


def test_beneficial_action_ignores_harmful_or_wrong_item():
    registry = SkillRegistry()
    assert registry.beneficial_action({"actionbar": [{**FIRST_AID_KIT_ACTION, "is_harmful": True}]}, 175241) is None
    assert registry.beneficial_action({"actionbar": [FIRST_AID_KIT_ACTION]}, 999) is None
    assert registry.beneficial_action({"actionbar": [FIRST_AID_KIT_ACTION]}, None) is None


def test_assist_available_when_matching_friendly_target_and_item():
    w = world(target=BJORN_TARGET, actionbar=[FIRST_AID_KIT_ACTION])
    proposal = Proposal.make("ASSIST", "test", {"guid": "Creature-1", "item_id": 175241})
    assert SkillRegistry().available(proposal, w) is True


def test_assist_unavailable_when_target_is_hostile():
    w = world(target={**BJORN_TARGET, "attackable": True}, actionbar=[FIRST_AID_KIT_ACTION])
    proposal = Proposal.make("ASSIST", "test", {"guid": "Creature-1", "item_id": 175241})
    assert SkillRegistry().available(proposal, w) is False


def test_assist_unavailable_when_target_guid_mismatches():
    w = world(target=BJORN_TARGET, actionbar=[FIRST_AID_KIT_ACTION])
    proposal = Proposal.make("ASSIST", "test", {"guid": "Creature-OTHER", "item_id": 175241})
    assert SkillRegistry().available(proposal, w) is False


def test_assist_unavailable_when_item_not_on_actionbar():
    w = world(target=BJORN_TARGET, actionbar=[])
    proposal = Proposal.make("ASSIST", "test", {"guid": "Creature-1", "item_id": 175241})
    assert SkillRegistry().available(proposal, w) is False


# --- SkillRegistry.commands() ------------------------------------------------

def test_assist_is_reserved_for_the_canonical_quest_item_skill():
    w = world(target=BJORN_TARGET, actionbar=[FIRST_AID_KIT_ACTION])
    proposal = Proposal.make("ASSIST", "test", {"guid": "Creature-1", "item_id": 175241})
    import pytest
    with pytest.raises(ValueError, match="canonical quest skill"):
        SkillRegistry().commands(proposal, w)


# --- Planner: proposes ASSIST for a named, structured USE-on-unit objective -

def test_planner_proposes_assist_for_named_wounded_ally():
    w = world(target=BJORN_TARGET, actionbar=[FIRST_AID_KIT_ACTION], active_quests=[QUEST])
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), w, 1)
    assists = [p for p in proposals if p.skill == "ASSIST"]
    assert len(assists) == 1
    assert assists[0].parameters["item_id"] == 175241
    assert assists[0].parameters["guid"] == "Creature-1"


def test_planner_does_not_propose_assist_for_an_unnamed_target():
    other = {**BJORN_TARGET, "guid": "Creature-2", "name": "Some Random Critter"}
    w = world(target=other, actionbar=[FIRST_AID_KIT_ACTION], active_quests=[QUEST])
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), w, 1)
    assert not any(p.skill == "ASSIST" for p in proposals)


def test_planner_does_not_propose_assist_without_the_item_on_actionbar():
    w = world(target=BJORN_TARGET, actionbar=[], active_quests=[QUEST])
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), w, 1)
    assert not any(p.skill == "ASSIST" for p in proposals)


def test_planner_does_not_propose_assist_for_a_dead_named_target():
    w = world(target={**BJORN_TARGET, "dead": True}, actionbar=[FIRST_AID_KIT_ACTION], active_quests=[QUEST])
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), w, 1)
    assert not any(p.skill == "ASSIST" for p in proposals)


# --- End-to-end engine wiring -----------------------------------------------

def test_engine_assist_succeeds_on_objective_progress():
    agent = AutonomousAgent(RecordingExecutor(), bindings=_SelectedBindings())
    agent.set_goal("Questelj", 1.0)
    agent.set_mode("FULL_AI")
    now = 1.0
    quest = {"quest_id": 1, "title": "Emergency First Aid", "objectives": [
        {"type": "object", "description": "Use a First Aid Kit on Bjorn Stouthands, Kee-la, and Austin Huxworth",
         "required": 3, "current": 0, "target_object": {"item_id": 175241}}]}
    for _ in range(3):
        now += .3
        agent.tick({"session_id": "s", "frame_id": f"f{now}", "timestamp": now, "map_id": 1409,
                   "position": {"x": .5, "y": .5}, "orientation": 0, "player_present": True,
                   "world_map_open": False, "target": BJORN_TARGET, "actionbar": [FIRST_AID_KIT_ACTION],
                   "active_quests": [quest]}, now)
    assert agent.pending is not None and agent.pending.proposal.skill == "ASSIST"
    now += .3
    progressed_quest = {**quest, "objectives": [{**quest["objectives"][0], "current": 1}]}
    result = agent.tick({"session_id": "s", "frame_id": f"f{now}", "timestamp": now, "map_id": 1409,
                        "position": {"x": .5, "y": .5}, "orientation": 0, "player_present": True,
                        "world_map_open": False, "target": BJORN_TARGET, "actionbar": [FIRST_AID_KIT_ACTION],
                        "active_quests": [progressed_quest]}, now)
    assert result["result"]["outcome"] == "SUCCESS" and result["result"]["skill"] == "ASSIST"
