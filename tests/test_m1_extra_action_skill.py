from wowbot.agent.models import Attempt, Goal, Prediction, Proposal
from wowbot.agent.planner import QuestDomain
from wowbot.agent.world import WorldModel
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus
from wowbot.runtime import FailureReason
from wowbot.skills import ExtraActionHandler, QuestToolSkill


class _Bindings:
    def __init__(self, actions=("EXTRAACTIONBUTTON1",)):
        self.actions = set(actions)

    def contains(self, action):
        return action in self.actions


def _active(**params):
    payload = {"extra_action_type": "item", "extra_action_id": 9001,
               "quest_ids": [42], "objective_ids": ["42:use"], **params}
    attempt = Attempt("action", Proposal.make("EXTRA_ACTION", "test", payload), {}, "obs", 1., 9., (),
                      Prediction("prediction", "action", "state", 1., 9., "obs"))
    runtime = ActiveSkillRuntime()
    return runtime.start(intent=Intent("EXTRA_ACTION", payload, objective_ref="42:use"),
                         attempt=attempt, now=1., before_snapshot={"active_quests": [{
                             "quest_id": 42, "objectives": [{"objective_id": "use", "current": 0,
                                                                  "required": 1, "is_complete": False}],
                         }]})


def test_exact_exported_extra_action_uses_only_selected_cache_binding_and_quest_credit():
    skill = QuestToolSkill(_Bindings())
    state = _active()
    shown = {"extra_action": {"visible": True, "usable": True,
                               "action": "EXTRAACTIONBUTTON1", "action_type": "item", "action_id": 9001}}
    started = skill.begin(state, shown)
    assert started.status is SkillStatus.RUNNING
    assert started.commands[0].binding == "EXTRAACTIONBUTTON1"
    assert skill.verify(state, shown, 2.).status is SkillStatus.RUNNING
    credited = {"active_quests": [{"quest_id": 42, "objectives": [{"objective_id": "use", "current": 1,
                                                                         "required": 1, "is_complete": True}]}]}
    result = skill.verify(state, credited, 3.)
    assert result.status is SkillStatus.SUCCESS
    assert result.evidence == ("objective_changed:42:use",)


def test_extra_action_fails_closed_for_missing_cache_or_changed_action_identity():
    shown = {"extra_action": {"visible": True, "usable": True,
                               "action": "EXTRAACTIONBUTTON1", "action_type": "item", "action_id": 9001}}
    assert QuestToolSkill().begin(_active(), shown).status is SkillStatus.BLOCKED
    wrong = {"extra_action": {**shown["extra_action"], "action_id": 9002}}
    assert QuestToolSkill(_Bindings()).begin(_active(), wrong).status is SkillStatus.FAILURE


def _planner_world():
    world = WorldModel()
    raw = {"quest_id": 42, "is_complete": False, "special_item": {"item_id": 9001},
           "objectives": [{"objective_id": "use", "type": "USE_OBJECT", "current": 0,
                           "required": 1, "is_complete": False}]}
    world.quest_model.ingest([raw], "obs", 1.)
    world.state = {"monotonic_time": 1., "map_id": 1409, "target": {}, "mouseover": {},
                   "cursor_position": {}, "active_quests": [raw], "quest_locations": [],
                   "extra_action": {"visible": True, "usable": True, "action": "EXTRAACTIONBUTTON1",
                                    "action_type": "item", "action_id": 9001}}
    return world


def test_planner_admits_only_exact_active_quest_special_item_action():
    world = _planner_world()
    proposal = next(item for item in QuestDomain().propose(world, Goal.parse("Quest", 1.))
                    if item.skill == "EXTRA_ACTION")
    assert proposal.parameters["authorization"] == "EXACT_ACTIVE_QUEST_SPECIAL_ITEM"
    assert proposal.parameters["extra_action_id"] == 9001

    world.state["extra_action"]["action_id"] = 9002
    assert not any(item.skill == "EXTRA_ACTION"
                   for item in QuestDomain().propose(world, Goal.parse("Quest", 1.)))


def test_non_item_extra_action_requires_explicit_exact_goal_authorization():
    world = _planner_world()
    world.state["extra_action"].update({"action_type": "spell", "action_id": 77})
    assert not any(item.skill == "EXTRA_ACTION"
                   for item in QuestDomain().propose(world, Goal.parse("Quest", 1.)))
    goal = Goal.parse("Quest", 1., {"allow_extra_action": True,
                                     "extra_action_type": "spell", "extra_action_id": 77})
    proposal = next(item for item in QuestDomain().propose(world, goal) if item.skill == "EXTRA_ACTION")
    assert proposal.parameters["authorization"] == "EXPLICIT_GOAL_EXACT_ACTION"


def test_extra_action_handler_target_and_range_contracts_fail_closed():
    assert QuestToolSkill is ExtraActionHandler
    params = {"guid": "Creature-1", "target_required": True,
              "range_required": True}
    state = _active(**params)
    shown = {"target": {"guid": "Creature-1"}, "extra_action": {
        "visible": True, "usable": True, "in_range": False,
        "action": "EXTRAACTIONBUTTON1", "action_type": "item",
        "action_id": 9001}}
    result = ExtraActionHandler(_Bindings()).begin(state, shown)
    assert result.reason is FailureReason.OUT_OF_RANGE
