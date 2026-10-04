from wowbot.agent.quest_model import QuestModel, objective_type
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.agent.quest_state import ObjectiveState, QuestState


def test_objective_normalization_preserves_unknown_and_ambiguity():
    assert objective_type({"raw_type": "monster", "description": "Something"})[0] == "KILL"
    assert objective_type({"description": "Speak with Captain Garrick"})[:2] == ("TALK_TO", .65)
    kind, confidence, candidates = objective_type({"description": "Find and collect supplies"})
    assert kind == "UNKNOWN" and confidence == .45
    assert {item["type"] for item in candidates} == {"FIND", "COLLECT"}


def test_structured_quest_history_graph_and_dependencies():
    model = QuestModel()
    quest = {"quest_id": 7, "title": "Test", "objectives": [
        {"description": "Speak with A", "type": "TALK", "current": 1, "required": 1},
        {"description": "Collect 3 kits", "raw_type": "item", "current": 0, "required": 3,
         "dependencies": [0], "branch_type": "SEQUENTIAL", "map_id": 1409, "x": .2, "y": .3},
        {"description": "Optional unknown", "optional": True},
    ]}
    model.ingest([quest], "obs-1", 1)
    record = model.records[7]
    assert record.objectives[0].type == "TALK_TO" and record.objectives[0].completion_state == "COMPLETE"
    assert record.objectives[1].target_location["coordinate_space"] == "NORMALIZED_MAP"
    assert record.objectives[1].dependencies == ("7:0",)
    assert {item.objective_id for item in model.ready()} == {"7:1", "7:2"}
    graph = model.graph()
    assert graph["edges"] == [{"from": "7:0", "to": "7:1", "branch_type": "SEQUENTIAL",
                                "optional": False, "condition": None,
                                "condition_state": "NOT_APPLICABLE", "condition_evidence": []}]
    model.ingest([{**quest, "objectives": [{**quest["objectives"][0]},
        {**quest["objectives"][1], "current": 2}, quest["objectives"][2]]}], "obs-2", 2)
    assert len(model.records[7].history) == 2


def test_missing_quest_is_absent_not_silently_turned_in():
    model = QuestModel()
    model.ingest([{"quest_id": 7, "objectives": []}], "obs-1", 1)
    model.ingest([], "obs-2", 2)
    assert model.records[7].current_state == "ABSENT"
    assert model.records[7].history[-1]["state"] == "ABSENT"
    assert model.records[7].lifecycle_state is QuestState.ABSENT


def test_lifecycle_keeps_objective_completion_distinct_from_turned_in_completion():
    model = QuestModel()
    model.ingest([{"quest_id": 9, "objectives": [{"type": "KILL", "current": 1, "required": 1}]}], "obs", 1)
    assert model.records[9].current_state == "ACTIVE"  # legacy activity/readiness surface
    assert model.records[9].lifecycle_state is QuestState.OBJECTIVES_COMPLETE
    model.ingest([{"quest_id": 9, "is_ready_to_turn_in": True, "objectives": []}], "ready", 2)
    assert model.records[9].lifecycle_state is QuestState.READY_TO_TURN_IN


def test_objective_lifecycle_is_explicit_without_promoting_a_failed_attempt_to_progress():
    model = QuestModel()
    model.ingest([{"quest_id": 11, "objectives": [
        {"objective_id": "waiting", "type": "TALK"},
        {"objective_id": "running", "type": "KILL", "current": 1, "required": 3},
        {"objective_id": "done", "type": "KILL", "current": 3, "required": 3},
        {"objective_id": "retry", "type": "INTERACT", "is_failed_retryable": True},
    ]}], "obs", 1)
    statuses = {item.objective_id: item.status for item in model.records[11].objectives}
    assert statuses == {"waiting": ObjectiveState.PENDING, "running": ObjectiveState.ACTIVE,
                        "done": ObjectiveState.COMPLETE, "retry": ObjectiveState.FAILED_RETRYABLE}
    assert model.records[11].objectives[3].failure_memory_key == ("11", "retry")


def test_explicit_quest_lifecycle_beliefs_are_preserved_with_provenance():
    model = QuestModel()
    model.ingest([{"quest_id": 10, "is_available": True, "confidence": .8,
                   "giver_belief": {"source": "MOUSEOVER"},
                   "turnin_belief": {"source": "QUEST_API"},
                   "reward_belief": {"source": "QUEST_UI"}, "objectives": []}], "obs", 4)
    record = model.records[10]
    assert record.lifecycle_state is QuestState.AVAILABLE
    assert record.confidence == .8
    assert record.giver_belief == {"source": "MOUSEOVER"}
    assert record.last_updated_at == 4


def test_quest_planner_uses_only_dependency_ready_graph_nodes():
    world = WorldModel()
    world.ingest(Observation.create({"session_id": "s", "frame_id": "f", "timestamp": 1,
        "map_id": 1409, "position": {"x": .5, "y": .5}, "orientation": 0,
        "player_present": True, "world_map_open": False, "active_quests": [{"quest_id": 7, "objectives": [
            {"type": "TALK", "current": 0, "required": 1, "map_id": 1409, "x": .4, "y": .4,
             "world_position": {"x": -400., "y": -2500., "instance_id": 2175,
                                "ui_map_id": 1409, "coordinate_space": "WORLD_YARDS"}},
            {"type": "COLLECT", "current": 0, "required": 1, "dependencies": [0],
             "map_id": 1409, "x": .8, "y": .8,
             "world_position": {"x": -800., "y": -2900., "instance_id": 2175,
                                "ui_map_id": 1409, "coordinate_space": "WORLD_YARDS"}}]}],
        "player_world_position": {"x": -350., "y": -2450., "instance_id": 2175,
                                  "coordinate_space": "WORLD_YARDS"}}, 1))
    choices = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world, 1)
    moves = [item for item in choices if item.skill == "MOVE"]
    assert len(moves) == 1 and moves[0].parameters["objective_id"] == "7:0"


def test_localized_generic_semantics_and_ambiguous_text_stay_conservative():
    assert objective_type({"description": "Beszélj Garrick kapitánnyal"})[0] == "TALK_TO"
    assert objective_type({"description": "Öld meg a murlocokat"})[0] == "KILL"
    assert objective_type({"description": "Gyűjts 3 gyógynövényt"})[0] == "COLLECT"
    kind, confidence, candidates = objective_type({"description": "Keresd meg és gyűjtsd össze a ládákat"})
    assert kind == "UNKNOWN" and confidence == .45
    assert {item["type"] for item in candidates} == {"FIND", "COLLECT"}


def test_structured_target_item_event_extraction_preserves_provenance():
    model = QuestModel()
    model.ingest([{"quest_id": 8, "objectives": [
        {"raw_type": "monster", "target_npc_id": 123, "target_name": "Murloc", "required": 2},
        {"raw_type": "item", "item_id": 456, "required": 3},
        {"type": "ESCORT"}]}], "obs", 1)
    record = model.records[8]
    assert record.known_entities[0] == {"npc_id": 123, "name": "Murloc", "source": "QUEST_API"}
    assert record.required_items[0]["item_id"] == 456
    assert record.required_events == ["ESCORT"]


def test_quest_and_conditional_dependencies_require_explicit_completion():
    model = QuestModel()
    model.ingest([
        {"quest_id": 1, "is_complete": False, "objectives": []},
        {"quest_id": 2, "dependencies": [1], "objectives": [{"type": "TALK"}]},
        {"quest_id": 3, "objectives": [{"type": "TALK", "branch_type": "CONDITIONAL", "condition": False}]},
    ], "obs1", 1)
    assert model.ready() == []
    model.ingest([
        {"quest_id": 1, "is_complete": True, "objectives": []},
        {"quest_id": 2, "dependencies": [1], "objectives": [{"type": "TALK"}]},
        {"quest_id": 3, "objectives": [{"type": "TALK", "branch_type": "CONDITIONAL", "condition": True}]},
    ], "obs2", 2)
    assert {objective.objective_id for objective in model.ready()} == {"2:0", "3:0"}
    assert any(edge["branch_type"] == "QUEST_DEPENDENCY" for edge in model.graph()["edges"])


def test_explicit_sequential_order_is_inferred_but_parallel_order_is_not():
    model = QuestModel()
    model.ingest([{"quest_id": 11, "objectives": [
        {"objective_id": "first", "type": "TALK", "branch_type": "SEQUENTIAL"},
        {"objective_id": "second", "type": "KILL", "branch_type": "SEQUENTIAL"},
        {"objective_id": "parallel", "type": "COLLECT", "branch_type": "PARALLEL"},
    ]}], "obs", 1)
    assert model.records[11].objectives[1].dependencies == ("first",)
    assert model.records[11].objectives[2].dependencies == ()
    assert {item.objective_id for item in model.ready()} == {"first", "parallel"}
    assert model.readiness()["second"]["blockers"] == ["OBJECTIVE_DEPENDENCY:first"]


def test_conditional_state_is_explicit_and_unknown_remains_blocked():
    model = QuestModel()
    model.ingest([{"quest_id": 12, "objectives": [
        {"objective_id": "unknown", "type": "TALK", "branch_type": "CONDITIONAL",
         "condition": {"kind": "aura_present"}},
        {"objective_id": "satisfied", "type": "TALK", "branch_type": "CONDITIONAL",
         "condition": {"status": "SATISFIED"}},
    ]}], "condition-observation", 1)
    unknown, satisfied = model.records[12].objectives
    assert unknown.condition_state == "UNKNOWN"
    assert unknown.condition_evidence == ("condition-observation",)
    assert model.readiness()["unknown"]["status"] == "BLOCKED"
    assert model.readiness()["unknown"]["blockers"] == ["CONDITION_UNKNOWN"]
    assert satisfied in model.ready()


def test_undeclared_array_order_does_not_invent_sequence():
    model = QuestModel()
    model.ingest([{"quest_id": 13, "objectives": [
        {"objective_id": "a", "type": "TALK"}, {"objective_id": "b", "type": "KILL"}
    ]}], "obs", 1)
    assert {item.objective_id for item in model.ready()} == {"a", "b"}
    assert model.records[13].objectives[1].dependencies == ()


def test_quest_graph_exposes_only_explicit_typed_chain_relations():
    model = QuestModel()
    model.ingest([
        {"quest_id": 10, "title": "First", "state": "COMPLETED",
         "unlocks": [11], "follow_up_id": 11, "objectives": []},
        {"quest_id": 11, "title": "Second", "dependencies": [10],
         "exclusive_with": [12], "same_area_with": [13],
         "objectives": [{"type": "TALK"}]},
        {"quest_id": 99, "title": "Adjacent but unrelated", "objectives": []},
    ], "chain", 1.)

    graph = model.graph()
    assert {node["quest_id"] for node in graph["quest_nodes"]} == {10, 11, 99}
    assert {(edge["from"], edge["to"], edge["type"])
            for edge in graph["quest_edges"]} == {
        ("10", "11", "UNLOCKS"), ("10", "11", "FOLLOW_UP"),
        ("10", "11", "REQUIRES"), ("11", "12", "EXCLUSIVE_WITH"),
        ("11", "13", "SAME_AREA_SYNERGY"),
    }
    assert all("99" not in (edge["from"], edge["to"])
               for edge in graph["quest_edges"])
    assert model.records[11].chain_relations


def test_structured_entity_and_object_identity_drive_shared_skills_only():
    base = {"session_id": "s", "frame_id": "f", "timestamp": 1, "map_id": 1409,
            "position": {"x": .5, "y": .5}, "orientation": 0, "player_present": True,
            "world_map_open": False, "actionbar": []}
    talk_world = WorldModel()
    talk_world.ingest(Observation.create({**base,
        "target": {"guid": "npc", "npc_id": 123, "attackable": False},
        "active_quests": [{"quest_id": 9, "objectives": [{"type": "TALK", "target_npc_id": 123}]}]}, 1))
    talk = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), talk_world, 1)
    assert talk[0].skill == "TALK" and talk[0].parameters["objective_id"] == "9:0"

    use_world = WorldModel()
    use_world.ingest(Observation.create({**base, "target": None,
        "mouseover": {"object_id": 77}, "cursor_position": {"nx": .4, "ny": .6},
        "active_quests": [{"quest_id": 10, "objectives": [{"type": "USE_ITEM", "object_id": 77}]}]}, 1))
    use = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), use_world, 1)
    assert use[0].skill == "OBJECT_USE" and use[0].parameters["object_id"] == 77


def test_ready_to_turn_in_lifecycle_routes_to_shared_talk_skill_not_a_quest_specific_click():
    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "s", "frame_id": "turnin", "timestamp": 1, "map_id": 1409,
        "position": {"x": .5, "y": .5}, "orientation": 0, "player_present": True,
        "world_map_open": False,
        "target": {"guid": "giver", "attackable": False, "quest_role": "QUEST_TURN_IN"},
        "active_quests": [{"quest_id": 20, "is_ready_to_turn_in": True, "objectives": []}],
    }, 1))

    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world, 1)

    talk = next(item for item in proposals if item.skill == "TALK")
    assert talk.parameters["guid"] == "giver"
    assert talk.parameters["quest_id"] == 20
