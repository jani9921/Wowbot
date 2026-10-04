"""Live 2026-10-04 00:23: INTERACTTARGET on Alaria raised "You need to be
closer" (code 852) but INTERACT reported no_response: the event's addon
observed_at was 6 s behind the baseline snapshot clock."""
from wowbot.runtime import FailureReason
from wowbot.verification.interaction import InteractionVerifier

OLD = {"event_type": "UI_ERROR_MESSAGE", "sequence": 3652,
       "payload": {"error_code": 852, "message": "You need to be closer to interact with that target.",
                   "observed_at": 458910.169}}
NEW = {**OLD, "sequence": 3663, "payload": {**OLD["payload"], "observed_at": 458932.631}}
TARGET = {"guid": "Creature-0-3113-2175-63341-156607-00004115E3"}


def test_new_range_error_sequence_is_out_of_range_despite_clock_skew():
    before = {"monotonic_time": 458938.4, "events": [OLD], "target": TARGET}
    after = {"monotonic_time": 458939.0, "events": [OLD, NEW], "target": TARGET}
    result = InteractionVerifier().evaluate(before, after, expected_guid=TARGET["guid"])
    assert result.reason is FailureReason.OUT_OF_RANGE


def test_range_error_already_in_the_baseline_is_not_new():
    before = {"monotonic_time": 458900.0, "events": [OLD], "target": TARGET}
    after = {"monotonic_time": 458939.0, "events": [OLD], "target": TARGET}
    result = InteractionVerifier().evaluate(before, after, expected_guid=TARGET["guid"])
    assert result.reason is not FailureReason.OUT_OF_RANGE
