from wowbot.runtime import FailureReason
from wowbot.verification.combat import CombatVerifier


GUID = "Creature-0-0-0-0-12-00000001"


def test_objective_credit_alone_is_supporting_evidence_not_a_verified_kill():
    before = {"active_quests": [{"quest_id": 1, "objectives": [{"objective_id": 1, "current": 0}]}]}
    after = {"active_quests": [{"quest_id": 1, "objectives": [{"objective_id": 1, "current": 1}]}]}

    result = CombatVerifier().evaluate(before, after, expected_guid=GUID)

    assert not result.success
    assert result.confidence == .25
    assert result.reason is None


def test_same_guid_unit_died_event_confirms_kill_without_a_selected_target():
    after = {"events": [{"event_type": "UNIT_DIED", "payload": {"guid": GUID}}]}

    result = CombatVerifier().evaluate({}, after, expected_guid=GUID)

    assert result.success
    assert result.confidence == 1.0
    assert "unit_died_event" in result.evidence


def test_hp_zero_and_objective_credit_without_a_dead_event_stay_below_threshold():
    before = {"active_quests": [{"quest_id": 1, "objectives": [{"objective_id": 1, "current": 0}]}]}
    after = {
        "target": {"guid": GUID, "health": 0},
        "active_quests": [{"quest_id": 1, "objectives": [{"objective_id": 1, "current": 1}]}],
    }

    result = CombatVerifier().evaluate(before, after, expected_guid=GUID)

    assert not result.success
    assert result.confidence < CombatVerifier.DEAD_THRESHOLD


def test_correlated_target_disappearance_combat_end_and_credit_can_confirm_kill():
    before = {
        "is_in_combat": True,
        "target": {"guid": GUID, "health": 5},
        "active_quests": [{"quest_id": 1, "objectives": [{"objective_id": 1, "current": 0}]}],
    }
    after = {
        "is_in_combat": False,
        "target": {},
        "active_quests": [{"quest_id": 1, "objectives": [{"objective_id": 1, "current": 1}]}],
    }

    result = CombatVerifier().evaluate(before, after, expected_guid=GUID)

    assert result.success
    assert result.confidence >= CombatVerifier.DEAD_THRESHOLD


def test_different_selected_guid_stays_an_identity_failure_even_with_death_evidence():
    result = CombatVerifier().evaluate(
        {},
        {"target": {"guid": "Creature-other", "dead": True},
         "events": [{"event_type": "UNIT_DIED", "payload": {"guid": GUID}}]},
        expected_guid=GUID,
    )

    assert not result.success
    assert result.reason is FailureReason.IDENTITY_UNCERTAIN


def test_combat_end_alone_never_confirms_kill_and_duplicate_source_is_deduplicated():
    verifier = CombatVerifier()
    ended = verifier.evaluate(
        {"is_in_combat": True, "target": {"guid": GUID}},
        {"is_in_combat": False, "target": {"guid": GUID}},
        expected_guid=GUID)
    assert not ended.success and ended.confidence == .25

    duplicated = verifier.fuse_dead_evidence(tuple(
        verifier.dead_evidence({}, {
            "events": [
                {"event_type": "UNIT_DIED", "payload": {"guid": GUID}},
                {"event_type": "UNIT_DIED", "payload": {"guid": GUID}},
            ]}, expected_guid=GUID)))
    assert duplicated == 1.0
