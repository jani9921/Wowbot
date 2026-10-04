from wowbot.agent.active_perception import ActivePerception
from wowbot.agent.memory import AgentMemory
from wowbot.agent.models import Goal, Observation
from wowbot.agent.planner import Planner
from wowbot.agent.quest_model import QuestModel
from wowbot.agent.quest_semantics import (objective_subject, resolve_entity_candidates,
                                          resolve_location_candidates, talk_to_subject)
from wowbot.agent.skills import SkillRegistry
from wowbot.agent.world import WorldModel
from wowbot.vision.entity_memory import EntityMemory


def quest_state(**overrides):
    value = {"session_id": "quest-patch", "frame_id": "q1", "timestamp": 1,
             "monotonic_time": 1, "map_id": 1409,
             "position": {"x": .5, "y": .5}, "orientation": 0,
             "player_present": True, "world_map_open": False,
             "active_quests": []}
    value.update(overrides)
    return value


def marker(track="track-1"):
    return {"track_id": track, "kind": "unknown_subject_candidate",
            "detector_kind": "unknown_subject_candidate", "source": "WORLD3D",
            "semantic_type": "UNKNOWN", "inspectable": True,
            "stable_frames": 3, "confidence": .7, "x": .4, "y": .6,
            "visual_signature": {"signature_id": "appearance-1",
                                 "representation_space": "WORLD3D"}}


def seed_entity(memory):
    for at in (1., 2., 3.):
        memory.record_mouseover({"npc_id": 111, "name": "Hogger", "unit_type": "NPC"},
                                map_id=1409, map_x=.42, map_y=.61,
                                zone="Elwynn Forest", observed_at=at)


def test_talk_subject_and_objective_subject_are_generic_hypotheses():
    assert talk_to_subject({"description": "Speak with Marshal Dughan about the ritual"}) == "marshal dughan"
    assert talk_to_subject({"description": "Report to Elling Trias"}) == "elling trias"
    assert objective_subject({"type": "KILL", "description": "Hogger slain: 0/1"}) == "hogger"
    assert objective_subject({"type": "COLLECT", "description": "Collect Linen"}) is None


def test_entity_and_context_location_candidates_are_hypotheses(tmp_path):
    entities = EntityMemory(tmp_path / "entities.sqlite3")
    seed_entity(entities)
    objective = {"type": "KILL", "description": "Hogger slain: 0/1"}
    candidates = resolve_entity_candidates(objective, entities)
    locations = resolve_location_candidates(candidates, entities, as_of=10.)
    assert candidates[0]["identity_key"] == "npc:111"
    assert candidates[0]["source"] == "ENTITY_MEMORY_NAME_LOOKUP"
    assert locations[0]["source"] == "ENTITY_MEMORY_LOCATION"
    assert locations[0]["confidence"] <= candidates[0]["confidence"]
    assert locations[0]["phase"] is None and locations[0]["instance_id"] is None


def test_structured_identity_prevents_name_lookup(tmp_path):
    entities = EntityMemory(tmp_path / "entities.sqlite3")
    seed_entity(entities)
    objective = {"type": "KILL", "description": "Hogger slain: 0/1",
                 "target_entity": {"npc_id": 111, "name": "Hogger"}}
    assert resolve_entity_candidates(objective, entities) == ()


def test_world_model_and_planner_use_low_priority_location_hypothesis(tmp_path):
    entities = EntityMemory(tmp_path / "entities.sqlite3")
    seed_entity(entities)
    world = WorldModel(entity_memory=entities)
    world.ingest(Observation.create(quest_state(active_quests=[{
        "quest_id": 1, "objectives": [{"type": "monster",
        "description": "Hogger slain: 0/1", "required": 1, "current": 0}]}]), 1))
    objective = world.quest_model.records[1].objectives[0]
    assert objective.entity_candidates and objective.location_candidates
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world, 1)
    move = next(item for item in proposals if item.parameters.get("hypothesis_source") == "ENTITY_MEMORY_LOCATION")
    assert move.priority == 35 and move.confidence < 1
    assert move.parameters["hypothesis_identity_key"] == "npc:111"


def test_confirmed_objective_location_wins_without_hypothesis_move(tmp_path):
    entities = EntityMemory(tmp_path / "entities.sqlite3")
    seed_entity(entities)
    world = WorldModel(entity_memory=entities)
    world.ingest(Observation.create(quest_state(active_quests=[{
        "quest_id": 1, "objectives": [{"type": "monster",
        "description": "Hogger slain: 0/1", "required": 1, "current": 0,
        "target_location": {"map_id": 1409, "x": .9, "y": .9}}]}]), 1))
    proposals = Planner(SkillRegistry()).candidates(Goal.parse("Questelj", 1), world, 1)
    objective_moves = [item for item in proposals if item.skill == "MOVE"
                       and item.parameters.get("objective_id")]
    assert len(objective_moves) == 1
    assert objective_moves[0].parameters["x"] == .9
    assert not objective_moves[0].parameters.get("hypothesis_source")


def test_rejection_memory_survives_track_change_and_is_map_scoped(tmp_path):
    memory = AgentMemory(tmp_path / "agent.sqlite3")
    first = marker("old-track")
    for at in (1., 32., 63.):
        memory.record_rejection(first, map_id=1409, reason="expected_observation_missing", at=at)
    same_appearance = marker("new-track")
    assert memory.rejection_status(same_appearance, map_id=1409, at=64)["belief"] == "REJECTED"
    assert memory.rejection_status(same_appearance, map_id=1, at=64)["belief"] == "UNKNOWN"
    memory.record_rejection_contradiction(same_appearance, map_id=1409, at=65)
    status = memory.rejection_status(first, map_id=1409, at=65)
    assert status["belief"] != "REJECTED" and status["contradictions"] == 1


def test_active_perception_suppresses_rejected_appearance(tmp_path):
    memory = AgentMemory(tmp_path / "agent.sqlite3")
    item = marker()
    for at in (1., 32., 63.):
        memory.record_rejection(item, map_id=1409, reason="expected_observation_missing", at=at)
    world = WorldModel()
    world.ingest(Observation.create(quest_state(monotonic_time=4), 4))
    world.last_received = 64
    world.state["monotonic_time"] = 64
    result = ActivePerception(memory).evaluate(item, world, Goal.parse("Questelj", 1))
    assert result["rejection"]["belief"] == "REJECTED"
    assert result["expected_information_gain"] == 0


def test_target_commitment_uses_reidentified_entity_not_track_id():
    item = marker("new-track")
    world = WorldModel()
    payload = quest_state(target={"guid": "Creature-1", "npc_id": 111,
                                  "name": "Hogger", "dead": False},
                          visual_candidates=[item],
                          visual_recognition_candidates=[{
                              "track_id": "new-track", "entity_candidates": [
                                  {"identity_key": "npc:111", "status": "SUPPORTED"}]}])
    world.ingest(Observation.create(payload, 1))
    inspections = Planner(SkillRegistry()).inspections(world, 1, goal=Goal.parse("Questelj", 1))
    assert inspections == []


def test_engine_failures_persist_rejection_across_visual_track_ids(tmp_path):
    from test_agent_core import agent, state

    memory = AgentMemory(tmp_path / "agent.sqlite3")
    value, _ = agent(memory=memory)
    for start, track in ((1, "track-a"), (32, "track-b"), (63, "track-c")):
        item = marker(track)
        value.tick(state(start, visual_candidates=[item]), start)
        assert value.pending and value.pending.proposal.skill == "INSPECT"
        value.tick(state(start+6, visual_candidates=[item],
                         cursor_position={"nx": .4, "ny": .6}), start+6)
        assert value.last_result["skill"] == "INSPECT"
        assert value.last_result["outcome"] == "FAILURE"
    rejected = memory.rejection_status(marker("track-d"), map_id=1609, at=67)
    assert rejected["belief"] == "REJECTED" and rejected["failures"] == 3
    value.tick(state(67, visual_candidates=[marker("track-d")]), 67)
    assert not value.pending or value.pending.proposal.skill != "INSPECT"


def test_first_independent_zero_information_hover_is_immediately_suppressed(tmp_path):
    memory = AgentMemory(tmp_path / "agent.sqlite3")
    item = marker()
    first = memory.record_rejection(item, map_id=1409,
                                    reason="valid_hover_no_information", at=1.)
    assert first["belief"] == "SUPPRESSED"
    assert first["failures"] == 1
    assert memory.rejection_status(item, map_id=1409, at=17.)["belief"] == "CANDIDATE"


def test_correlated_retry_does_not_count_as_an_independent_rejection(tmp_path):
    memory = AgentMemory(tmp_path / "agent.sqlite3")
    item = marker()
    memory.record_rejection(item, map_id=1409, reason="valid_hover_no_information", at=1.,
                            evidence_group="frame-a")
    status = memory.record_rejection(item, map_id=1409,
                                     reason="valid_hover_no_information", at=8.,
                                     evidence_group="frame-b")
    assert status["failures"] == 1


def test_coarse_visual_signature_survives_small_bbox_and_lighting_change(tmp_path):
    memory = AgentMemory(tmp_path / "agent.sqlite3")
    first = marker()
    first["visual_signature"] = {
        "representation_space": "WORLD3D", "signature_id": "exact-a",
        "shape": {"aspect": .51, "w_bin": 4, "h_bin": 10},
        "appearance": {"brightness_bin": 12, "saturation_bin": 20,
                       "red_bin": 24, "green_bin": 18, "blue_bin": 5,
                       "fill_bin": 17}}
    changed = marker("new-track")
    changed["visual_signature"] = {
        "representation_space": "WORLD3D", "signature_id": "exact-b",
        "shape": {"aspect": .53, "w_bin": 5, "h_bin": 12},
        "appearance": {"brightness_bin": 13, "saturation_bin": 19,
                       "red_bin": 25, "green_bin": 18, "blue_bin": 6,
                       "fill_bin": 18}}
    memory.record_rejection(first, map_id=1409,
                            reason="valid_hover_no_information", at=1.)
    assert memory.rejection_status(changed, map_id=1409, at=2.)["belief"] == "SUPPRESSED"


def test_cursor_miss_is_not_learned_as_object_rejection(tmp_path):
    from test_agent_core import agent, state

    memory = AgentMemory(tmp_path / "agent.sqlite3")
    value, _ = agent(memory=memory)
    item = marker()
    value.tick(state(1, visual_candidates=[item]), 1)
    assert value.pending and value.pending.proposal.skill == "INSPECT"
    value.tick(state(7, visual_candidates=[item],
                     cursor_position={"nx": .1, "ny": .1}), 7)
    assert value.last_result["inspection_quality"]["valid_zero_information"] is False
    assert memory.rejection_status(item, map_id=1609, at=7)["belief"] == "UNKNOWN"


def test_first_valid_failed_hover_suppresses_reidentified_track_in_engine(tmp_path):
    from test_agent_core import agent, state

    memory = AgentMemory(tmp_path / "agent.sqlite3")
    value, _ = agent(memory=memory)
    first = marker("track-a")
    value.tick(state(1, visual_candidates=[first]), 1)
    value.tick(state(7, visual_candidates=[first],
                     cursor_position={"nx": .4, "ny": .6}), 7)
    status = memory.rejection_status(marker("track-b"), map_id=1609, at=7)
    assert status["belief"] == "SUPPRESSED" and status["independent_trials"] == 1
    value.tick(state(8, visual_candidates=[marker("track-b")]), 8)
    assert not value.pending or value.pending.proposal.skill != "INSPECT"
