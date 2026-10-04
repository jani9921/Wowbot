import pytest

from wowbot.agent.active_perception import ActivePerception


def test_probe_fsm_records_bounded_information_gain_without_input_authority():
    value = ActivePerception()
    requested = value.request_probe(probe_id="probe:1", track_id="WORLD3D:7",
                                    baseline_confidence=.42, at=1.)
    assert requested["state"] == "REQUESTED" and requested["accepted"] is True
    assert value.select_probe_action("hover_candidate", at=1.1)["state"] == "SELECT_ACTION"
    waiting = value.mark_probe_dispatched(at=1.2, timeout=.5)
    assert waiting["state"] == "WAIT_OBSERVATION"
    result = value.evaluate_probe(at=1.3, confidence=.62)

    assert result["state"] == "SUCCESS"
    assert [row["state"] for row in result["history"]] == [
        "REQUESTED", "SELECT_ACTION", "EXECUTE_PROBE", "WAIT_OBSERVATION",
        "EVALUATE_GAIN", "SUCCESS"]
    assert result["action_authority"] == "NONE" and result["input_sent"] is False


def test_probe_fsm_aborts_immediately_on_combat_preemption_and_rejects_overlap():
    value = ActivePerception()
    value.request_probe(probe_id="probe:1", track_id="WORLD3D:7", baseline_confidence=.5, at=1.)
    conflict = value.request_probe(probe_id="probe:2", track_id="WORLD3D:8", baseline_confidence=.5, at=1.1)
    assert conflict["accepted"] is False
    value.select_probe_action("wait_tooltip", at=1.2)
    value.mark_probe_dispatched(at=1.3)
    result = value.evaluate_probe(at=1.4, confidence=None, combat_preempted=True)
    assert result["state"] == "FAILED"
    assert result["history"][-1]["reason"] == "combat_safety_preemption"


def test_probe_fsm_requires_valid_transition_order():
    value = ActivePerception()
    with pytest.raises(RuntimeError, match="requires REQUESTED"):
        value.select_probe_action("hover_candidate", at=1.)
