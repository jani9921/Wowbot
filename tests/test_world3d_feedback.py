from wowbot.vision.world3d.feedback import apply_world3d_feedback


def track(track_id, confidence=.8):
    return {"track_id": track_id, "confidence": confidence,
            "temporal_state": "CONFIRMED", "role_beliefs": [],
            "distance_belief": {"bucket": "MID", "metric_value": None},
            "interactability_belief": {"confidence": .8, "fact": False}}


def test_death_transition_links_corpse_to_source_entity_track():
    result, events = apply_world3d_feedback(
        [track("alive"), track("corpse")],
        {"world3d_death_events": [{
            "source_entity_track_id": "alive", "corpse_track_id": "corpse",
            "source": "COMBAT_LOG", "confidence": .95,
        }]}, observed_at=2.)
    by_id = {row["track_id"]: row for row in result}

    assert by_id["alive"]["temporal_state"] == "DEAD"
    assert by_id["alive"]["alive_belief"]["label"] == "DEAD"
    assert by_id["corpse"]["source_entity_track_id"] == "alive"
    assert by_id["corpse"]["corpse_belief"]["belief"] == "CONFIRMED"
    assert events[0]["event_type"] == "WORLD3D_DEATH_TRANSITION"


def test_no_credit_penalizes_role_belief_not_detector_confidence():
    original = track("mob", confidence=.87)
    result, _ = apply_world3d_feedback([original], {"quest_no_credit_events": [{
        "kind": "QUEST_NO_CREDIT", "track_id": "mob", "role_label": "QUEST_OBJECTIVE_MOB",
        "penalty": .4,
    }]}, observed_at=2.)

    assert result[0]["confidence"] == .87
    assert result[0]["quest_role_penalty"]["detector_confidence_unchanged"] is True
    assert result[0]["role_beliefs"][-1]["belief"] == "CONTRADICTED"


def test_interaction_and_combat_feedback_update_only_relevant_beliefs():
    rows = [
        {"kind": "INTERACTION_FAILURE", "track_id": "npc", "reason": "OUT_OF_RANGE"},
        {"kind": "COMBAT_ERROR", "track_id": "npc", "reason": "FACING_WRONG_WAY"},
        {"kind": "COMBAT_ERROR", "track_id": "npc", "reason": "LINE_OF_SIGHT"},
        {"kind": "COMBAT_ERROR", "track_id": "npc", "reason": "TARGET_LOST"},
    ]
    result, events = apply_world3d_feedback(
        [track("npc")], {"world3d_feedback": rows}, observed_at=3.)
    candidate = result[0]

    assert candidate["distance_belief"]["relative_lower_bound"] == "BEYOND_ACTION_RANGE"
    assert candidate["facing_feedback"]["correction_required"] is True
    assert candidate["local_geometry_feedback"]["obstacle_evidence"] == "LOS_BLOCKED"
    assert candidate["reacquire_request"]["input_authority"] is False
    assert len(events) == 4

