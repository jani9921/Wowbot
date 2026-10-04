from types import SimpleNamespace

from wowbot.agent.quest_model import QuestModel
from wowbot.agent.quest_runtime import QuestExecutionRuntime


def model(*ids):
    value = QuestModel()
    value.ingest([{"quest_id": identifier, "objectives": []} for identifier in ids], "o", 1.)
    return value


def test_primary_quest_uses_explicit_selection_and_does_not_switch_silently():
    runtime = QuestExecutionRuntime()
    goal = SimpleNamespace(domain="QUEST", parameters={"quest_id": 2})
    state = runtime.observe(goal, model(1, 2), {}, 1.)
    assert state.quest_id == "2" and state.status == "ACTIVE"
    state = runtime.observe(goal, model(1), {}, 2.)
    assert state.quest_id == "2" and state.status == "NOT_ACTIVE_REASSESS"


def test_primary_quest_auto_selects_only_unambiguous_single_active_quest():
    runtime = QuestExecutionRuntime()
    goal = SimpleNamespace(domain="QUEST", parameters={})
    assert runtime.observe(goal, model(1, 2), {}, 1.).status == "NEEDS_SELECTION"
    assert runtime.observe(goal, model(2), {}, 2.).quest_id == "2"


def test_primary_runtime_selects_one_ready_objective_and_exposes_location_phase():
    value = QuestModel()
    value.ingest([{"quest_id": 7, "objectives": [
        {"objective_id": "7:talk", "type": "TALK_TO", "target_location": {"map_id": 1, "x": .2, "y": .3}},
        {"objective_id": "7:kill", "type": "KILL", "target_location": {"map_id": 2, "x": .5, "y": .6}},
    ]}], "o", 1.)
    runtime = QuestExecutionRuntime()
    goal = SimpleNamespace(domain="QUEST", parameters={"quest_id": 7})

    state = runtime.observe(goal, value, {"map_id": 1}, 1.)
    assert state.objective_id == "7:kill"
    assert state.objective_type == "KILL"
    assert state.phase == "NAVIGATE_GLOBAL"
    # A second independent ready objective must not silently steal ownership.
    assert runtime.observe(goal, value, {"map_id": 2}, 2.).objective_id == "7:kill"


def test_completed_primary_quest_exposes_field_turnin_without_silent_switch():
    value = QuestModel()
    value.ingest([{"quest_id": 7, "is_complete": True, "objectives": []}], "o", 1.)
    runtime = QuestExecutionRuntime()
    goal = SimpleNamespace(domain="QUEST", parameters={"quest_id": 7})

    state = runtime.observe(goal, value, {"quest_ui_action": "COMPLETE"}, 1.)
    assert state.status == "COMPLETED"
    assert state.phase == "FIELD_TURN_IN"
    assert state.completion_mode == "FIELD_TURN_IN"


def test_completed_primary_quest_preserves_distinct_auto_and_special_completion_surfaces():
    value = QuestModel()
    value.ingest([{"quest_id": 7, "is_complete": True, "objectives": []}], "o", 1.)
    goal = SimpleNamespace(domain="QUEST", parameters={"quest_id": 7})
    assert QuestExecutionRuntime().observe(goal, value, {"quest_completion_mode": "AUTO_COMPLETE"}, 1.).phase == "VERIFY_COMPLETE"
    assert QuestExecutionRuntime().observe(goal, value, {"quest_completion_mode": "SPECIAL_UI"}, 1.).phase == "HANDLE_SPECIAL_UI"


def test_stage_change_invalidates_old_objective_selection_before_reclassification():
    goal = SimpleNamespace(domain="QUEST", parameters={"quest_id": 7})
    runtime = QuestExecutionRuntime()
    first = QuestModel()
    first.ingest([{"quest_id": 7, "objectives": [
        {"objective_id": "7:a", "type": "KILL", "current": 0, "required": 1},
        {"objective_id": "7:b", "type": "TALK_TO", "current": 0, "required": 1},
    ]}], "o1", 1.)
    assert runtime.observe(goal, first, {}, 1.).objective_id == "7:a"

    progressed = QuestModel()
    progressed.ingest([{"quest_id": 7, "objectives": [
        {"objective_id": "7:a", "type": "KILL", "current": 1, "required": 1, "is_complete": True},
        {"objective_id": "7:b", "type": "TALK_TO", "current": 0, "required": 1},
    ]}], "o2", 2.)
    state = runtime.observe(goal, progressed, {}, 2.)
    assert state.objective_id == "7:b"
    assert state.stage_revision == 1
    assert state.last_stage_transition["reason"] == "quest_model_stage_changed"
