from wowbot.vision.world3d.cue_beliefs import derive_cue_beliefs


def test_corpse_lootability_requires_death_continuity_and_interact_cue():
    weak = derive_cue_beliefs(
        detector_kind="unknown_subject_candidate",
        candidate_labels=["learned_corpse_like"], appearance={}, confidence=.8)
    strong = derive_cue_beliefs(
        detector_kind="unknown_subject_candidate",
        candidate_labels=["learned_corpse_like", "interact_cue_like"],
        appearance={"death_confirmation": True, "source_track_id": "alive"},
        confidence=.8)

    assert weak["corpse_belief"]["lootable_belief"] == "UNKNOWN"
    assert strong["corpse_belief"]["belief"] == "SUPPORTED"
    assert strong["corpse_belief"]["lootable_belief"] == "CANDIDATE"
    assert strong["corpse_belief"]["fact"] is False


def test_quest_context_does_not_turn_non_object_into_quest_object():
    belief = derive_cue_beliefs(
        detector_kind="unknown_subject_candidate", candidate_labels=[],
        appearance={}, confidence=.8, quest_context_active=True)

    assert belief["object_belief"]["belief"] == "UNKNOWN"
    assert belief["object_belief"]["quest_role_belief"] == "UNKNOWN"
