"""Input-free quest-accept flow coordinator (DESIGN-047)."""
from __future__ import annotations

from enum import StrEnum

from .models import Goal, number
from wowbot.verification.quest_dialog import QuestDialogVerifier


class QuestAcceptPhase(StrEnum):
    LOCATE_QUEST_SOURCE = "LOCATE_QUEST_SOURCE"
    INTERACT = "INTERACT"
    READ_QUEST_OFFER = "READ_QUEST_OFFER"
    VALIDATE_QUEST = "VALIDATE_QUEST"
    ACCEPT = "ACCEPT"
    WAIT_STATE = "WAIT_STATE"
    VERIFY_ACTIVE = "VERIFY_ACTIVE"


class QuestAcceptFlow:
    """Coordinate evidence and intent; Interact/QuestDialog still execute."""

    def __init__(self, verifier: QuestDialogVerifier | None = None) -> None:
        self.verifier = verifier or QuestDialogVerifier()

    @staticmethod
    def locate_source(state: dict) -> dict | None:
        for candidate in (state.get("target") or {}, state.get("mouseover") or {}):
            roles = {str(value).upper() for value in candidate.get("roles", ())}
            if candidate.get("quest_giver") is True or "QUEST_GIVER" in roles:
                return candidate
        return None

    @staticmethod
    def read_offer(state: dict) -> dict | None:
        ui = state.get("quest_ui") or {}
        action = str(ui.get("action") or state.get("quest_ui_action") or "").upper()
        if not (ui.get("open") is True or state.get("quest_ui_open") is True) or action != "ACCEPT":
            return None
        quest_id = ui.get("quest_id") or state.get("quest_ui_quest_id")
        x = number(ui.get("x")) or number(state.get("quest_ui_x"))
        y = number(ui.get("y")) or number(state.get("quest_ui_y"))
        return {"quest_id": quest_id, "title": ui.get("title"), "x": x, "y": y}

    @staticmethod
    def matches_goal(offer: dict, goal: Goal | None) -> bool:
        parameters = (getattr(goal, "parameters", {}) or {}) if goal is not None else {}
        wanted = parameters.get("primary_quest_id") or parameters.get("quest_id")
        return wanted is None or (offer.get("quest_id") is not None
                                  and str(offer["quest_id"]) == str(wanted))

    @staticmethod
    def accept_command(offer: dict) -> dict | None:
        x, y = number(offer.get("x")), number(offer.get("y"))
        if x is None or y is None or not (0 < x < 1 and 0 < y < 1):
            return None
        return {"x": x, "y": y, "action": "ACCEPT", "quest_id": offer.get("quest_id")}

    def verify_accepted(self, before: dict, after: dict, quest_id: object):
        return self.verifier.evaluate(before, after, quest_id=quest_id, action="ACCEPT")
