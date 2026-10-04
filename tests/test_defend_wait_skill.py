from types import SimpleNamespace

from wowbot.agent.models import Goal, Observation
from wowbot.agent.quest_planning import QuestDomain
from wowbot.agent.world import WorldModel
from wowbot.runtime import ActiveSkillRuntime, Intent, SkillStatus, FailureReason
from wowbot.skills import DefendWaitPhase, DefendWaitSkill


def active(before, *, deadline=20.):
    runtime = ActiveSkillRuntime()
    attempt = SimpleNamespace(deadline=deadline)
    state = runtime.start(
        intent=Intent("WAIT_EVENT", {
            "quest_ids": [7], "objective_ids": ["7:wait"]}),
        attempt=attempt, now=1., before_snapshot=before)
    return state


def quest_state(current=0, *, combat=False, target=None):
    return {
        "active_quests": [{"quest_id": 7, "objectives": [{
            "objective_id": "wait", "type": "WAIT", "current": current,
            "required": 1, "is_complete": current >= 1,
        }]}],
        "is_in_combat": combat,
        "target": target or {},
    }


def test_wait_event_is_stationary_and_only_quest_progress_is_success():
    skill = DefendWaitSkill()
    before = quest_state()
    state = active(before)
    started = skill.begin(state, before, 1.)
    assert started.status is SkillStatus.RUNNING and started.commands == ()
    assert state.phase == DefendWaitPhase.MONITOR
    assert skill.verify(state, before, 2.).status is SkillStatus.RUNNING
    progressed = skill.verify(state, quest_state(1), 3.)
    assert progressed.status is SkillStatus.SUCCESS
    assert "objective_changed:7:wait" in progressed.evidence


def test_combat_interrupt_replans_to_canonical_defend_and_timeout_is_bounded():
    skill = DefendWaitSkill()
    before = quest_state()
    state = active(before, deadline=5.)
    skill.begin(state, before, 1.)
    combat = skill.verify(state, quest_state(combat=True, target={
        "guid": "Creature-1", "attackable": True, "dead": False}), 2.)
    assert combat.status is SkillStatus.FAILURE
    assert combat.reason is FailureReason.INTERRUPTED
    assert state.phase == DefendWaitPhase.COMBAT_IF_REQUIRED

    state = active(before, deadline=5.)
    skill.begin(state, before, 1.)
    timeout = skill.verify(state, before, 5.)
    assert timeout.status is SkillStatus.FAILURE
    assert timeout.reason is FailureReason.TIMEOUT
    assert state.phase == DefendWaitPhase.TIMEOUT_REEVALUATE


def test_wait_objective_without_concrete_location_does_not_search_or_move():
    world = WorldModel()
    payload = {
        "session_id": "s", "frame_id": "f", "timestamp": 1.,
        "map_id": 1409, "position": {"x": .5, "y": .5},
        "active_quests": [{"quest_id": 7, "objectives": [{
            "objective_id": "wait", "type": "WAIT", "current": 0,
            "required": 1,
        }]}],
    }
    world.ingest(Observation.create(payload, 1.))
    proposals = QuestDomain().propose(
        world, Goal.parse("Questelj", 1., {"quest_id": 7}))
    waits = [item for item in proposals if item.skill == "WAIT_EVENT"]
    assert len(waits) == 1
    assert waits[0].parameters["objective_ids"] == ["wait"]
    assert not any(item.skill in {"MOVE", "SEARCH", "INSPECT", "OPEN_MAP"}
                   for item in proposals)
