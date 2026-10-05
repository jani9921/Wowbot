"""Pure before/after interaction evaluation."""
from __future__ import annotations

from wowbot.runtime import FailureReason, VerificationResult


FACING_TOKENS = ("facing", "in front of you", "behind you", "szembe", "előtted", "mögötted")
LOS_TOKENS = ("line of sight", "not in line", "látóvonal", "rálátás")
RANGE_ERROR_TOKENS = ("out of range", "too far", "need to be closer", "túl messze", "közelebb")


def classify_ui_error(message: str | None, code=None) -> str | None:
    """RANGE / FACING / LINE_OF_SIGHT for a client UI error, else None."""
    text = str(message or "").casefold()
    if code == 852 or any(token in text for token in RANGE_ERROR_TOKENS):
        return "RANGE"
    if any(token in text for token in FACING_TOKENS):
        return "FACING"
    if any(token in text for token in LOS_TOKENS):
        return "LINE_OF_SIGHT"
    return None


def new_ui_errors(before: dict, after: dict) -> list[dict]:
    """UI_ERROR_MESSAGE payloads newer than every event in the baseline.

    Sequence ordering (not the addon clock) decides "new"; see
    ``InteractionVerifier._range_event``.  The flattened ``ui_error`` is
    included when it changed sequence.
    """
    known = [event.get("sequence") for event in (before or {}).get("events") or ()
             if isinstance(event, dict) and isinstance(event.get("sequence"), int)]
    baseline = max(known) if known else None
    result = []
    for event in (after or {}).get("events") or ():
        if not isinstance(event, dict) or event.get("event_type") != "UI_ERROR_MESSAGE":
            continue
        sequence = event.get("sequence")
        if baseline is not None and isinstance(sequence, int) and sequence <= baseline:
            continue
        if baseline is None and not isinstance(sequence, int):
            continue
        result.append(event.get("payload") or {})
    if ((after or {}).get("ui_error") and (after or {}).get("ui_error_sequence")
            != (before or {}).get("ui_error_sequence")):
        result.append({"message": after.get("ui_error"), "error_code": after.get("ui_error_code")})
    return result


class InteractionVerifier:
    RANGE_TOKENS = ("out of range", "too far", "need to be closer", "túl messze", "közelebb")
    # ERR_GENERIC_NO_TARGET style codes vary; 852 is Retail 12.1's
    # "You need to be closer to interact with that target." (live 2026-10-01).
    RANGE_ERROR_CODES = frozenset({852})

    @classmethod
    def _range_event(cls, before: dict, after: dict) -> bool:
        """A client range error raised after this attempt began.

        Live 2026-10-01: four "You need to be closer" errors reached the agent
        as UI_ERROR_MESSAGE events, while the flattened ``ui_error`` field
        showed one of them, 3 s late, so INTERACT reported ``no_response``.
        """
        started = before.get("monotonic_time")
        try:
            started = float(started) - .25 if started is not None else None
        except (TypeError, ValueError):
            started = None
        code = after.get("ui_error_code")
        at = after.get("ui_error_at")
        if (code in cls.RANGE_ERROR_CODES and at is not None and started is not None
                and float(at) >= started
                and after.get("ui_error_sequence") != before.get("ui_error_sequence")):
            return True
        # Live 2026-10-04 00:23: the error's observed_at (458932.6) was 6 s
        # behind the FAST snapshot's monotonic_time, so the time test dropped
        # a fresh "need to be closer" and INTERACT reported no_response.  An
        # event sequence newer than every event already in the baseline is
        # new regardless of the clock.
        known = [event.get("sequence") for event in before.get("events") or ()
                 if isinstance(event, dict) and isinstance(event.get("sequence"), int)]
        baseline_sequence = max(known) if known else None
        for event in after.get("events") or ():
            if not isinstance(event, dict) or event.get("event_type") != "UI_ERROR_MESSAGE":
                continue
            payload = event.get("payload") or {}
            observed = payload.get("observed_at")
            sequence = event.get("sequence")
            if baseline_sequence is not None and isinstance(sequence, int):
                if sequence <= baseline_sequence:
                    continue
            elif started is None or observed is None or float(observed) < started:
                continue
            text = str(payload.get("message") or "").casefold()
            if (payload.get("error_code") in cls.RANGE_ERROR_CODES
                    or any(token in text for token in cls.RANGE_TOKENS)):
                return True
        return False

    def evaluate(self, before: dict, after: dict, *, expected_guid: str | None,
                 expected_result: str | None = None) -> VerificationResult:
        target = after.get("target") or {}
        if expected_guid and target.get("guid") not in {None, expected_guid}:
            return VerificationResult(False, .95, FailureReason.IDENTITY_UNCERTAIN)
        message = str(after.get("ui_error") or "").casefold()
        if any(token in message for token in self.RANGE_TOKENS) or self._range_event(before, after):
            return VerificationResult(False, .9, FailureReason.OUT_OF_RANGE, retry_recommended=True)
        if any(token in message for token in ("facing", "face the", "szembe")):
            return VerificationResult(False, .85, FailureReason.FACING_FAILED, retry_recommended=True)
        if any(token in message for token in (
                "line of sight", "not in line", "látóvonal")):
            return VerificationResult(False, .9, FailureReason.LINE_OF_SIGHT,
                                      retry_recommended=True)
        if any(token in message for token in (
                "not ready", "please wait", "busy", "még nem")):
            return VerificationResult(False, .7, FailureReason.NO_RESPONSE,
                                      retry_recommended=True)
        if after.get("in_vehicle") is True and before.get("in_vehicle") is not True:
            # A used vehicle NPC seats the player (addon 0.9.47).
            return VerificationResult(True, .9, None, ("vehicle_entered",))
        old_quest, new_quest = before.get("quest_ui") or {}, after.get("quest_ui") or {}
        quest_opened = new_quest.get("open") is True and (
            old_quest.get("open") is not True
            or (new_quest.get("action"), new_quest.get("quest_id")) !=
               (old_quest.get("action"), old_quest.get("quest_id")))
        fast_quest_opened = after.get("quest_ui_open") is True and (
            before.get("quest_ui_open") is not True
            or (after.get("quest_ui_action"), after.get("quest_ui_quest_id")) !=
               (before.get("quest_ui_action"), before.get("quest_ui_quest_id")))
        old_gossip, new_gossip = before.get("gossip_ui") or {}, after.get("gossip_ui") or {}
        gossip_opened = new_gossip.get("open") is True and (
            old_gossip.get("open") is not True or new_gossip != old_gossip)
        quest_changed = self._quest_signature(before) != self._quest_signature(after)
        # Live 2026-10-04 (Quartermaster Richter): the shop opened but the
        # verifier only knew quest/gossip frames and reported no_response.
        vendor_opened = ((after.get("vendor_ui") or {}).get("open") is True
                         and (before.get("vendor_ui") or {}).get("open") is not True)
        expected = str(expected_result or "").upper()
        opened = quest_opened or fast_quest_opened or gossip_opened
        if expected and opened and not self._matches_expected(
                expected, new_quest, after, gossip_opened, quest_changed):
            return VerificationResult(False, .9, FailureReason.WRONG_UI)
        if quest_opened or fast_quest_opened or gossip_opened or quest_changed or vendor_opened:
            evidence = tuple(name for name, present in (
                ("quest_ui", quest_opened), ("fast_quest_ui", fast_quest_opened),
                ("gossip_ui", gossip_opened), ("quest_state", quest_changed),
                ("vendor_ui", vendor_opened)) if present)
            return VerificationResult(True, .95 if quest_changed else .85, None, evidence)
        return VerificationResult(False, .0, None)

    @staticmethod
    def _matches_expected(expected: str, quest_ui: dict, after: dict,
                          gossip_opened: bool, quest_changed: bool) -> bool:
        """Interpret only explicit expected interaction outcomes.

        With no expected result, generic Interact remains deliberately broad:
        any verified appropriate UI/quest transition is sufficient.  Once an
        intent names its outcome, an unrelated but open UI cannot falsely
        complete it.
        """
        action = str(quest_ui.get("action") or after.get("quest_ui_action") or "").upper()
        if expected in {"GOSSIP_OPEN", "DIALOG_OPEN"}:
            return gossip_opened
        if expected == "QUEST_OFFER":
            return action in {"OFFER", "AVAILABLE", "ACCEPT"}
        if expected == "QUEST_COMPLETE":
            return action in {"COMPLETE", "TURN_IN", "REWARD"}
        if expected in {"OBJECT_STATE_CHANGE", "OBJECTIVE_PROGRESS", "ITEM_GAIN", "SCRIPT_EVENT"}:
            return quest_changed
        # Unknown named outcomes must not be silently treated as success.
        return False

    @staticmethod
    def _quest_signature(state: dict) -> tuple:
        return tuple(sorted((str(q.get("quest_id")), bool(q.get("is_complete")),
                             tuple((o.get("current"), o.get("required"), bool(o.get("is_complete")))
                                   for o in q.get("objectives") or ()))
                            for q in state.get("active_quests") or ()))
