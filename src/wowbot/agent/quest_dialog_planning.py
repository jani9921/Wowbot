"""Quest-dialog proposal policy; it selects no input and mutates no state."""
from __future__ import annotations

from .models import Goal, Proposal, number
from .quest_offer_selector import QuestOfferSelector
from .quest_reward_selector import QuestRewardSelector
from .quest_accept_flow import QuestAcceptFlow


class QuestDialogPlanningPolicy:
    """Translate explicit addon UI facts into generic quest-dialog proposals."""

    # User 2026-10-03: when one NPC offers several quests, take the first,
    # then the second, the third ...  If Retail closes the dialog after an
    # accept, the same NPC is spoken to again while offers remain.
    PENDING_OFFER_SECONDS = 45.

    def __init__(self) -> None:
        self.offer_selector = QuestOfferSelector()
        self.reward_selector = QuestRewardSelector()
        self.accept_flow = QuestAcceptFlow()
        self.pending_offers: dict | None = None

    def _remember_offers(self, state: dict, rows: list[dict]) -> None:
        now = number(state.get("monotonic_time"))
        guid = str((state.get("target") or {}).get("guid") or "")
        available = {str(row.get("quest_id")) for row in rows
                     if str(row.get("kind") or "").upper() == "AVAILABLE"
                     and row.get("quest_id") is not None}
        if guid and available and now is not None:
            self.pending_offers = {"guid": guid, "quest_ids": available, "at": now}

    def _pending_offer_interact(self, state: dict) -> Proposal | None:
        memory = getattr(self, "pending_offers", None)
        if not memory:
            return None
        now = number(state.get("monotonic_time"))
        if now is None or not 0 <= now - memory["at"] <= self.PENDING_OFFER_SECONDS:
            self.pending_offers = None
            return None
        taken = {str(quest.get("quest_id")) for quest in state.get("active_quests") or ()
                 if isinstance(quest, dict)}
        remaining = memory["quest_ids"] - taken
        if not remaining:
            self.pending_offers = None
            return None
        target = state.get("target") or {}
        if (str(target.get("guid") or "") != memory["guid"] or state.get("is_in_combat")
                or target.get("attackable", target.get("is_attackable")) is True):
            return None
        return Proposal.make(
            "INTERACT", "Ugyanannál az NPC-nél még felvehető quest maradt: újra megszólítás",
            {"guid": memory["guid"], "pending_quest_ids": sorted(remaining)}, priority=95)

    def propose(self, state: dict, goal: Goal | None, *, primary_quest_id: str = "") -> list[Proposal]:
        result: list[Proposal] = []
        ui = state.get("quest_ui") or {}
        dialog_open = ui.get("open") is True or state.get("quest_ui_open") is True
        action = str(ui.get("action") or state.get("quest_ui_action") or "").upper()
        completion_mode = str(
            state.get("quest_completion_mode")
            or (state.get("primary_quest") or {}).get("completion_mode") or "UNKNOWN").upper()
        dialog_skill = ("FIELD_TURN_IN"
                        if completion_mode == "FIELD_TURN_IN"
                        and action in {"COMPLETE", "TURN_IN", "REWARD_SELECT"}
                        else "QUEST_DIALOG")
        if dialog_open and action == "REWARD_SELECT":
            parameters = getattr(goal, "parameters", {}) or {}
            selection = self.reward_selector.select(
                ui.get("reward_choices"),
                choice_index=parameters.get("reward_choice_index"),
                item_id=parameters.get("reward_item_id"),
                # User 2026-10-04: a reward window must not stall questing;
                # an explicit goal policy (or BLOCKED) still wins.
                policy=parameters.get("reward_policy") or "AUTO",
            )
            quest_id = ui.get("quest_id") or state.get("quest_ui_quest_id")
            if selection.choice is not None:
                choice = selection.choice
                result.append(Proposal.make(
                    dialog_skill, "Addon által igazolt, explicit quest-jutalom választása",
                    {"x": choice["x"], "y": choice["y"], "action": "REWARD_SELECT",
                     "quest_id": quest_id, "reward_choice_index": choice["index"],
                     "reward_item_id": choice.get("item_id"),
                     "completion_mode": completion_mode}, priority=94,
                ))
            else:
                result.append(Proposal.make(
                    "WAIT", "Quest-jutalom kiválasztása explicit szabályt vagy ellenőrzött sort igényel",
                    {"reason": selection.reason, "quest_id": quest_id,
                     "reward_choices": ui.get("reward_choices") or []},
                    confidence=1., priority=95,
                ))
        if dialog_open and action == "ACCEPT":
            offer = self.accept_flow.read_offer(state)
            command = (self.accept_flow.accept_command(offer)
                       if offer and self.accept_flow.matches_goal(offer, goal) else None)
            if command is not None:
                result.append(Proposal.make(
                    "QUEST_DIALOG", "Célhoz egyező, addon által igazolt quest ajánlat elfogadása",
                    command, priority=90,
                ))
            elif offer is not None and not self.accept_flow.matches_goal(offer, goal):
                result.append(Proposal.make(
                    "WAIT", "A nyitott quest ajánlat nem egyezik az explicit céllal",
                    {"reason": "quest_offer_goal_mismatch",
                     "offered_quest_id": offer.get("quest_id")},
                    confidence=1., priority=95,
                ))
        if dialog_open and action in {"COMPLETE", "CONTINUE", "TURN_IN"}:
            x = number(ui.get("x")) or number(state.get("quest_ui_x"))
            y = number(ui.get("y")) or number(state.get("quest_ui_y"))
            if x is not None and y is not None and x > 0 and y > 0:
                result.append(Proposal.make(
                    dialog_skill, "A megnyitott quest ablak API által jelzett gombja",
                    {"x": x, "y": y, "action": action,
                     "quest_id": ui.get("quest_id") or state.get("quest_ui_quest_id"),
                     "completion_mode": completion_mode}, priority=90,
                ))
        explicit_quest_id = None
        if goal is not None:
            explicit_quest_id = ((getattr(goal, "parameters", {}) or {}).get("primary_quest_id")
                                 or (getattr(goal, "parameters", {}) or {}).get("quest_id"))
        gossip_rows = []
        observed_gossip_rows = []
        for entry in ui.get("entries", state.get("quest_ui_entries", [])):
            if not isinstance(entry, dict):
                continue
            quest_id = entry.get("quest_id")
            kind = str(entry.get("kind") or "").upper()
            if (entry.get("acceptable", entry.get("is_acceptable"))
                    and quest_id is not None and kind in {"AVAILABLE", "COMPLETE"}):
                observed_gossip_rows.append(entry)
                x, y = number(entry.get("x")), number(entry.get("y"))
                if x is None or y is None or not (0 < x < 1 and 0 < y < 1):
                    continue
                row = {"x": number(entry.get("x")), "y": number(entry.get("y")),
                       "quest_id": quest_id, "gossip_kind": kind}
                if entry.get("title"):
                    row["title"] = str(entry["title"])
                gossip_rows.append(row)
        if dialog_open and observed_gossip_rows:
            self._remember_offers(state, observed_gossip_rows)
        elif not dialog_open:
            pending = self._pending_offer_interact(state)
            if pending is not None:
                result.append(pending)
        if dialog_open and observed_gossip_rows and not gossip_rows:
            # A visible gossip/quest list is a modal UI context.  If the addon
            # can identify the rows but cannot export an exact click point,
            # fail closed in that UI instead of allowing world navigation or
            # visual approach to click through/behind it.
            result.append(Proposal.make(
                "WAIT", "A nyitott questlista soraihoz nincs hiteles kattintási koordináta",
                {"reason": "quest_dialog_rows_unaddressable",
                 "offered_quest_ids": sorted({str(row.get("quest_id"))
                                               for row in observed_gossip_rows})},
                confidence=1., priority=110,
            ))
        objective_context = dict((getattr(goal, "parameters", {}) or {}) if goal is not None else {})
        # Only a quest the user named is a hard filter.  The runtime's current
        # quest is a preference: live 2026-10-02 21:45 the just-turned-in
        # primary quest filtered out both offered quests and the agent waited
        # 38 s in front of an open list.
        if primary_quest_id:
            objective_context.setdefault("active_quest_id", primary_quest_id)
        selection = self.offer_selector.select(
            gossip_rows, str(explicit_quest_id) if explicit_quest_id is not None else None,
            objective=objective_context)
        if selection.requires_explicit_selection:
            result.append(Proposal.make(
                "WAIT", "Több addon által igazolt quest-ajánlat látható; explicit quest_id szükséges",
                {"reason": "quest_offer_selection_required",
                 "offered_quest_ids": list(selection.offered_quest_ids)},
                confidence=1., priority=81,
            ))
        for row in selection.rows:
            result.append(Proposal.make(
                "QUEST_DIALOG", "Addon által igazolt, quest-célhoz kötött gossip sor kiválasztása",
                {**row, "action": "GOSSIP_SELECT"}, priority=80,
            ))
        return result
