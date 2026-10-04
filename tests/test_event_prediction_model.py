from wowbot.agent.engine import AutonomousAgent
from wowbot.agent.executor import RecordingExecutor
from wowbot.agent.memory import AgentMemory
from wowbot.agent.models import Mode, Observation
from wowbot.agent.world import WorldModel
from test_agent_core import state


def test_first_class_event_links_observation_and_updates_quest_lifecycle(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    world = WorldModel()
    first = Observation.create(state(active_quests=[{"quest_id": 42, "objectives": []}]), 1)
    world.ingest(first); memory.observe(first)
    second = Observation.create(state(2, active_quests=[], event_sequence=1, events=[
        {"sequence": 1, "event_type": "QUEST_TURNED_IN", "source": "WOW_EVENT",
         "payload": {"quest_id": 42}}]), 2)
    world.ingest(second); memory.observe(second)
    event = world.event_records[-1]
    assert event.event_type == "QUEST_STATE_CHANGED" or event.event_type == "QUEST_TURNED_IN"
    turned_in = next(item for item in world.event_records if item.event_type == "QUEST_TURNED_IN")
    assert turned_in.observation_id == second.observation_id and turned_in.quest_ids == (42,)
    assert world.quest_model.records[42].current_state == "TURNED_IN"
    assert memory.events(second.session_id)[0]["quest_ids"] == [42]


def test_failed_expected_observation_creates_prediction_error():
    agent = AutonomousAgent(RecordingExecutor())
    agent.set_goal("Menj oda", 1, {"destination": {"map_id": 1609, "x": .5, "y": .4}})
    agent.set_mode(Mode.FULL_AI)
    agent.tick(state(movement={"speed": 0, "moving": False}), 1)
    # V5 requires a hard-stuck window, not the former short pulse timeout.
    for index, at in enumerate((1.4, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8, 4.2, 4.6), 2):
        agent.tick(state(at, movement={"speed": 0, "moving": False}), at)
    error = agent.world.prediction_errors[-1]
    assert error.expected == "reach_destination"
    assert error.reason == "supported_stuck"
    assert error.baseline_observation_id != error.observed_observation_id
    assert error.investigation == "COLLECT_EVIDENCE_AND_REPLAN"
    verification = agent.world.verifications[-1]
    assert verification.action_id == error.action_id
    assert verification.outcome == "FAILURE"


def test_unrelated_spellcast_does_not_verify_fishing():
    agent = AutonomousAgent(RecordingExecutor())
    agent.set_goal("Fishingelj", 1)
    agent.set_mode(Mode.FULL_AI)
    action = {"kind": "spell", "id": 100, "name": "Fishing", "action": "ACTIONBUTTON1",
              "is_usable": True, "cooldown_remaining": 0}
    agent.tick(state(actionbar=[action]), 1)
    assert agent.pending and agent.pending.proposal.skill == "FISH"
    unrelated = {"sequence": 1, "event_type": "SPELLCAST_SUCCEEDED", "payload": {"spell_id": 999}}
    agent.tick(state(2, actionbar=[action], event_sequence=1, events=[unrelated], is_casting=True), 2)
    assert agent.pending and agent.goal.completed_steps == 0


def test_visual_track_lifecycle_events_are_first_class_and_persisted(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    world = WorldModel(event_sink=memory.save_event_record)
    world.ingest(Observation.create(state(), 1))
    tentative = {"session_id": "test:player-1", "timestamp": 1.1, "frame_id": "v1",
                 "visual_candidates": [{"track_id": "MINIMAP_CV:1", "kind": "minimap_candidate",
                                          "track_state": "TENTATIVE", "confidence": .7}]}
    world.ingest(Observation.create(tentative, 1.1, "MINIMAP_CV"))
    stable = {**tentative, "timestamp": 1.2, "frame_id": "v2",
              "visual_candidates": [{**tentative["visual_candidates"][0], "track_state": "STABLE",
                                       "stable_frames": 3}]}
    world.ingest(Observation.create(stable, 1.2, "MINIMAP_CV"))
    for index in range(3):
        world.ingest(Observation.create({**tentative, "timestamp": 2+index, "frame_id": f"empty-{index}",
                                         "visual_candidates": []}, 2+index, "MINIMAP_CV"))
    lifecycle = [event for event in world.event_records if event.event_type.startswith("VISUAL_TRACK_")]
    assert [event.event_type for event in lifecycle] == [
        "VISUAL_TRACK_APPEARED", "VISUAL_TRACK_STABILIZED", "VISUAL_TRACK_LOST"]
    assert all(event.marker_ids == ("MINIMAP_CV:1",) for event in lifecycle)
    assert [row["event_type"] for row in memory.events("test:player-1")
            if row["event_type"].startswith("VISUAL_TRACK_")] == [
        "VISUAL_TRACK_APPEARED", "VISUAL_TRACK_STABILIZED", "VISUAL_TRACK_LOST"]


def test_entity_and_belief_lifecycle_events_keep_observation_provenance():
    world = WorldModel()
    target = {"guid": "Creature-1", "npc_id": 9, "unit_type": "NPC", "name": "Guide",
              "world_position": {"x": .2, "y": .3}}
    first = Observation.create(state(target=target), 1)
    world.ingest(first)
    moved = Observation.create(state(2, target={**target, "world_position": {"x": .25, "y": .35}}), 2)
    world.ingest(moved)
    kinds = {event.event_type for event in world.event_records}
    assert {"ENTITY_APPEARED", "ENTITY_LOCATION_CHANGED", "BELIEF_CHANGED"} <= kinds
    changed = next(event for event in world.event_records if event.event_type == "ENTITY_LOCATION_CHANGED")
    assert changed.observation_id == moved.observation_id
    assert any(edge.subject == f"event:{changed.event_id}" and edge.object == f"observation:{moved.observation_id}"
               for edge in world.relations.values())


def test_temporal_world3d_state_does_not_emit_a_belief_event_storm():
    world = WorldModel()
    world.ingest(Observation.create(state(1), 1))
    for index in range(100):
        at = 1.1 + index * .02
        world.ingest(Observation.create({
            "session_id": world.session_id,
            "frame_id": f"vision-{index}",
            "visual_candidates": [{
                "track_id": "WORLD3D:1", "detector_kind": "unknown_subject_candidate",
                "confidence": .5 + (index % 2) * .1,
            }],
            "world3d_batch": {"frame_id": index, "latency_ms": index % 7},
            "camera_state": {"yaw_delta": index * .01},
            "local_traversability": {"center_clear": bool(index % 2)},
        }, at, "WORLD3D"))

    noisy = [event for event in world.event_records if event.event_type in {
        "BELIEF_CHANGED", "CONTRADICTION_DETECTED", "CONTRADICTION_RESOLVED"}]
    assert noisy == []
    assert world.query.belief("world3d_batch", 3.2)["status"] != "UNKNOWN"


def test_non_action_entity_prediction_is_verified_by_later_observation():
    world = WorldModel()
    target = {"npc_id": 9, "guid": "Creature-9", "unit_type": "NPC",
              "world_position": {"x": .2, "y": .3}}
    world.ingest(Observation.create(state(target=target), 1))
    pending = world.query.predictions(kind="ENTITY_PERSISTENCE", status="PENDING")
    assert pending and pending[0].action_id == "WORLD_MODEL"
    assert pending[0].predicted_state["tolerance"] == .03
    world.ingest(Observation.create(state(2, target={**target,
        "world_position": {"x": .205, "y": .302}}), 2))
    verified = world.query.predictions(kind="ENTITY_PERSISTENCE", status="SUCCESS")
    assert verified and verified[0].reason == "entity_observed_near_predicted_location"
    assert any(event.event_type == "PREDICTION_VERIFIED" for event in world.event_records)


def test_world_prediction_mismatch_revises_model_but_absence_does_not():
    target = {"npc_id": 9, "unit_type": "NPC", "world_position": {"x": .2, "y": .3}}
    world = WorldModel()
    world.ingest(Observation.create(state(target=target), 1))
    world.ingest(Observation.create(state(2, target={**target,
        "world_position": {"x": .8, "y": .8}}), 2))
    assert world.model_revision == 2
    assert world.prediction_errors[-1].failure_type == "WORLD_MODEL_MISMATCH"
    assert any(event.event_type == "PREDICTION_ERROR" for event in world.event_records)

    absent = WorldModel()
    absent.ingest(Observation.create(state(target=target), 1))
    absent.ingest(Observation.create(state(12, target=None), 12))
    prediction = absent.query.predictions(kind="ENTITY_PERSISTENCE")[0]
    assert prediction.status == "UNOBSERVED"
    assert not absent.prediction_errors


def test_quest_acceptance_predicts_marker_and_requires_sufficient_surface_coverage():
    accepted = state(event_sequence=1, events=[{
        "sequence": 1, "event_type": "QUEST_ACCEPTED", "payload": {"quest_id": 42}}],
        active_quests=[{"quest_id": 42, "objectives": []}])
    world = WorldModel()
    world.ingest(Observation.create(accepted, 1))
    prediction = world.query.predictions(kind="QUEST_MARKER_APPEARANCE", status="PENDING")[0]
    assert prediction.subject == "quest:42"
    marker = {"session_id": "test:player-1", "timestamp": 2, "frame_id": "map-1",
              "map_marker_observations": [{"quest_id": 42, "semantic_type": "QUEST_RELATED"}]}
    world.ingest(Observation.create(marker, 2, "SPATIAL_MEMORY"))
    assert world.query.predictions(kind="QUEST_MARKER_APPEARANCE", status="SUCCESS")

    missing = WorldModel()
    missing.ingest(Observation.create(accepted, 1))
    for index, at in enumerate((14., 15., 16.)):
        missing.ingest(Observation.create({"session_id": "test:player-1", "timestamp": at,
            "frame_id": f"empty-map-{index}", "visual_candidates": []}, at, "MINIMAP_CV"))
    failed = missing.query.predictions(kind="QUEST_MARKER_APPEARANCE")[0]
    assert failed.status == "FAILURE"
    assert len(failed.predicted_state["coverage_observations"]) == 3
    assert missing.prediction_errors[-1].failure_type == "WORLD_MODEL_MISMATCH"


def test_quest_marker_prediction_expires_unobserved_without_surface_coverage():
    accepted = state(event_sequence=1, events=[{
        "sequence": 1, "event_type": "QUEST_ACCEPTED", "payload": {"quest_id": 42}}],
        active_quests=[{"quest_id": 42, "objectives": []}])
    world = WorldModel()
    world.ingest(Observation.create(accepted, 1))
    world.ingest(Observation.create(state(19, active_quests=accepted["active_quests"]), 19))
    prediction = world.query.predictions(kind="QUEST_MARKER_APPEARANCE")[0]
    assert prediction.status == "UNOBSERVED"
    assert not world.prediction_errors


def test_world_hydrates_from_persisted_observations_in_recorded_order(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    world = WorldModel(None, memory.save_world_relation, memory.save_event_record)
    addon = Observation.create(state(target={"npc_id": 9, "guid": "Creature-9", "unit_type": "NPC",
        "world_position": {"x": .2, "y": .3}}, active_quests=[{"quest_id": 42,
        "objectives": [{"type": "KILL", "required": 1, "current": 0}]}]), 1)
    visual = Observation.create({"session_id": "test:player-1", "timestamp": 1.1, "frame_id": "v1",
        "visual_candidates": [{"track_id": "WORLD3D:1", "kind": "entity_candidate",
                                "track_state": "TENTATIVE", "confidence": .7}]}, 1.1, "WORLD3D")
    for observation in (addon, visual):
        assert world.ingest(observation)
        memory.observe(observation)
    hydrated = memory.hydrate_world("test:player-1")
    assert [item.observation_id for item in hydrated.history] == [addon.observation_id, visual.observation_id]
    assert set(hydrated.entities) == set(world.entities)
    assert hydrated.quest_model.snapshot() == world.quest_model.snapshot()
    assert set(hydrated.relations) == set(world.relations)
    assert [event.event_type for event in hydrated.event_records] == [
        event.event_type for event in world.event_records]
