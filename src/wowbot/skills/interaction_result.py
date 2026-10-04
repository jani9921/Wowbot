"""Normalize interaction verification into recovery-safe result classes.

Verification remains the authority for whether an interaction worked.  This
small adapter deliberately does *not* infer an entity role; it only gives the
interaction FSM and diagnostics a stable description of what happened.
"""
from __future__ import annotations

from enum import StrEnum

from wowbot.runtime import FailureReason


class InteractionResultKind(StrEnum):
    SUCCESS = "SUCCESS"
    TOO_FAR = "TOO_FAR"
    FACING = "FACING"
    LOS = "LOS"
    CURSOR_MISS = "CURSOR_MISS"
    WRONG_ENTITY = "WRONG_ENTITY"
    ENTITY_MOVED = "ENTITY_MOVED"
    UI_NOT_READY = "UI_NOT_READY"
    TARGET_LOST = "TARGET_LOST"
    UNKNOWN = "UNKNOWN"
    # Compatibility aliases; iteration exposes only the canonical matrix.
    OUT_OF_RANGE = "TOO_FAR"
    NO_RESPONSE = "UI_NOT_READY"
    WRONG_UI = "UNKNOWN"
    FAILED = "UNKNOWN"


class InteractionEffectKind(StrEnum):
    """Observable postcondition kind; distinct from recovery classification."""
    GOSSIP_OPEN = "GOSSIP_OPEN"
    QUEST_DETAIL_OPEN = "QUEST_DETAIL_OPEN"
    QUEST_PROGRESS_OPEN = "QUEST_PROGRESS_OPEN"
    QUEST_COMPLETE_OPEN = "QUEST_COMPLETE_OPEN"
    MERCHANT_OPEN = "MERCHANT_OPEN"
    LOOT_OPEN = "LOOT_OPEN"
    OBJECT_ACTIVATED = "OBJECT_ACTIVATED"
    TARGET_CHANGED = "TARGET_CHANGED"
    NOTHING = "NOTHING"
    UNKNOWN = "UNKNOWN"


class InteractionResultClassifier:
    """Classify verifier output without issuing input or retrying itself."""

    _BY_REASON = {
        FailureReason.OUT_OF_RANGE: InteractionResultKind.TOO_FAR,
        FailureReason.FACING_FAILED: InteractionResultKind.FACING,
        FailureReason.LINE_OF_SIGHT: InteractionResultKind.LOS,
        FailureReason.LOW_CONFIDENCE: InteractionResultKind.CURSOR_MISS,
        FailureReason.IDENTITY_UNCERTAIN: InteractionResultKind.WRONG_ENTITY,
        FailureReason.INVALID_TARGET: InteractionResultKind.WRONG_ENTITY,
        FailureReason.TARGET_MOVED: InteractionResultKind.ENTITY_MOVED,
        FailureReason.TARGET_LOST: InteractionResultKind.TARGET_LOST,
        FailureReason.TARGET_NOT_FOUND: InteractionResultKind.TARGET_LOST,
        FailureReason.NO_RESPONSE: InteractionResultKind.NO_RESPONSE,
    }

    def classify(
        self,
        reason: FailureReason | None,
        before_snapshot: dict | None = None,
        after_snapshot: dict | None = None,
    ) -> InteractionResultKind:
        if reason is None:
            return InteractionResultKind.SUCCESS
        mapped = self._BY_REASON.get(reason)
        if mapped is not None:
            return mapped
        after_snapshot = after_snapshot or {}
        return InteractionResultKind.UNKNOWN

    @staticmethod
    def classify_effect(before_snapshot: dict | None, after_snapshot: dict | None) -> InteractionEffectKind:
        """Describe only an observable state delta, never a guessed outcome."""
        before_snapshot, after_snapshot = before_snapshot or {}, after_snapshot or {}
        events = tuple(event for event in after_snapshot.get("events") or ()
                       if isinstance(event, dict))
        event_names = {str(event.get("event_type") or "").upper() for event in events}
        gossip = after_snapshot.get("gossip_ui") or {}
        if gossip.get("open") is True and (before_snapshot.get("gossip_ui") or {}).get("open") is not True:
            return InteractionEffectKind.GOSSIP_OPEN
        if "GOSSIP_SHOW" in event_names:
            return InteractionEffectKind.GOSSIP_OPEN
        quest = after_snapshot.get("quest_ui") or {}
        action = str(quest.get("action") or after_snapshot.get("quest_ui_action") or "").upper()
        opened = quest.get("open") is True or after_snapshot.get("quest_ui_open") is True
        if opened:
            if action in {"OFFER", "AVAILABLE", "ACCEPT", "DETAIL"}:
                return InteractionEffectKind.QUEST_DETAIL_OPEN
            if action in {"PROGRESS", "IN_PROGRESS"}:
                return InteractionEffectKind.QUEST_PROGRESS_OPEN
            if action in {"COMPLETE", "TURN_IN", "REWARD"}:
                return InteractionEffectKind.QUEST_COMPLETE_OPEN
            return InteractionEffectKind.UNKNOWN
        if "QUEST_DETAIL" in event_names:
            return InteractionEffectKind.QUEST_DETAIL_OPEN
        if "QUEST_PROGRESS" in event_names:
            return InteractionEffectKind.QUEST_PROGRESS_OPEN
        if event_names & {"QUEST_COMPLETE", "QUEST_FINISHED"}:
            return InteractionEffectKind.QUEST_COMPLETE_OPEN
        if ((after_snapshot.get("merchant_ui_open") is True
             and before_snapshot.get("merchant_ui_open") is not True)
                or "MERCHANT_SHOW" in event_names):
            return InteractionEffectKind.MERCHANT_OPEN
        if ((after_snapshot.get("loot_ui_open") is True
             and before_snapshot.get("loot_ui_open") is not True)
                or "LOOT_OPENED" in event_names):
            return InteractionEffectKind.LOOT_OPEN
        if ((after_snapshot.get("object_activated") is True
             and before_snapshot.get("object_activated") is not True)
                or event_names & {"OBJECT_ACTIVATED", "GAMEOBJECT_ACTIVATED"}
                or InteractionResultClassifier._object_state_changed(
                    before_snapshot, after_snapshot)):
            return InteractionEffectKind.OBJECT_ACTIVATED
        if after_snapshot.get("target") != before_snapshot.get("target"):
            return InteractionEffectKind.TARGET_CHANGED
        if (after_snapshot.get("unexpected_ui_open") or after_snapshot.get("wrong_dialog_open")
                or event_names & {"INTERACTION_RESULT", "UI_OPENED"}):
            return InteractionEffectKind.UNKNOWN
        return InteractionEffectKind.NOTHING

    @staticmethod
    def _object_state_changed(before: dict, after: dict) -> bool:
        old, new = before.get("interactable_object"), after.get("interactable_object")
        if not isinstance(old, dict):
            return False
        if new is None:
            return True
        if not isinstance(new, dict):
            return False
        identity = str(old.get("guid") or old.get("object_id") or "")
        if identity and identity != str(new.get("guid") or new.get("object_id") or ""):
            return False
        return old.get("state") != new.get("state")
