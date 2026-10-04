"""Pure M0 loot outcome evaluation."""
from __future__ import annotations

from wowbot.runtime import FailureReason, VerificationResult


class LootVerifier:
    SUCCESS_THRESHOLD = .80

    def evaluate(self, before: dict, after: dict, *, corpse_guid: str | None,
                 expected_item_ids: tuple[int, ...] = ()) -> VerificationResult:
        events = self._new_events(before, after)
        source_events = [event for event in events if isinstance(event, dict)
                         and event.get("event_type") == "LOOT_RECEIVED"
                         and (not corpse_guid or not (event.get("payload") or {}).get("source_guid")
                              or str((event.get("payload") or {}).get("source_guid")) == corpse_guid)]
        loot_event = bool(source_events)
        before_inventory = before.get("inventory") or {}
        after_inventory = after.get("inventory") or {}
        gained_ids = self._gained_item_ids(before_inventory, after_inventory)
        expected = {int(item_id) for item_id in expected_item_ids}
        event_ids = {
            int(item_id) for event in source_events
            for item_id in ((event.get("payload") or {}).get("item_id"),
                            (event.get("payload") or {}).get("itemID"))
            if item_id is not None and str(item_id).lstrip("-").isdigit()
        }
        relevant_item = not expected or bool(expected.intersection(gained_ids | event_ids))
        inventory_changed = bool(gained_ids)
        objective_changed = self._objective_signature(before) != self._objective_signature(after)
        old_loot, new_loot = before.get("loot_ui") or {}, after.get("loot_ui") or {}
        loot_ui_opened = (new_loot.get("open") is True or after.get("loot_ui_open") is True) and (
            old_loot.get("open") is not True or new_loot != old_loot)
        corpse_lootable_changed = self._corpse_field_changed(
            before, after, corpse_guid, "lootable", true_to_false=True)
        corpse_interaction_changed = self._corpse_field_changed(
            before, after, corpse_guid, "interaction_state")
        # The addon emits LOOT_WINDOW_OPENED/CLOSED (Retail LOOT_OPENED and
        # LOOT_CLOSED).  With auto-loot the window opens and closes at once.
        event_types = [str(event.get("event_type") or "").upper() for event in events
                       if isinstance(event, dict)
                       and (not corpse_guid or not (event.get("payload") or {}).get("source_guid")
                            or str((event.get("payload") or {}).get("source_guid")) == corpse_guid)]
        event_loot_opened = any(kind in {"LOOT_OPENED", "LOOT_WINDOW_OPENED"} for kind in event_types)
        loot_window_cycled = event_loot_opened and any(
            kind in {"LOOT_CLOSED", "LOOT_WINDOW_CLOSED"} for kind in event_types)
        loot_ui_opened = loot_ui_opened or event_loot_opened
        if expected and (loot_event or inventory_changed) and relevant_item:
            evidence = tuple(name for name, value in (
                ("loot_received", loot_event), ("inventory_delta", inventory_changed),
                ("expected_item", True)) if value)
            return VerificationResult(True, 1. if loot_event else .85, None, evidence)
        # Some Retail quest items auto-consume or are not represented as a
        # stable inventory stack. A changed quest objective is still strong
        # post-interaction evidence, but cannot satisfy an explicitly declared
        # item-ID contract on its own.
        if objective_changed and not expected:
            return VerificationResult(True, .85, None, ("quest_objective_delta",))
        evidence_weights = {
            "loot_received": 1.0 if loot_event else 0.,
            "inventory_delta": .85 if inventory_changed else 0.,
            "loot_ui_open": .55 if loot_ui_opened else 0.,
            "loot_window_cycled": .80 if loot_window_cycled else 0.,
            "corpse_lootable_changed": .80 if corpse_lootable_changed else 0.,
            "corpse_interaction_changed": .75 if corpse_interaction_changed else 0.,
        }
        confidence = self._fuse(evidence_weights)
        evidence = tuple(name for name, weight in evidence_weights.items() if weight > 0.)
        if not expected and confidence >= self.SUCCESS_THRESHOLD:
            return VerificationResult(True, confidence, None, evidence)
        if evidence:
            return VerificationResult(False, confidence, None, evidence)
        error = str(after.get("ui_error") or "").casefold()
        if any(text in error for text in ("out of range", "need to be closer", "too far", "közelebb", "túl messze")):
            return VerificationResult(False, .9, FailureReason.OUT_OF_RANGE, retry_recommended=True)
        if any(text in error for text in ("not lootable", "nothing to loot", "nincs mit")):
            return VerificationResult(False, .9, FailureReason.NOT_LOOTABLE)
        return VerificationResult(False, .0, None)

    @staticmethod
    def _new_events(before: dict, after: dict) -> list:
        """Events emitted after the loot attempt began.

        ``events`` is a rolling buffer: an older LOOT_RECEIVED or window event
        must not verify a new click, so compare addon sequence numbers."""
        def sequence(event):
            value = event.get("sequence") if isinstance(event, dict) else None
            return value if isinstance(value, (int, float)) else None
        known = [sequence(event) for event in before.get("events") or ()]
        known = [value for value in known if value is not None]
        floor = before.get("event_sequence") if isinstance(before.get("event_sequence"), (int, float)) else None
        floor = max([*known, *([floor] if floor is not None else [])], default=None)
        events = list(after.get("events") or ())
        if floor is None:
            return events
        return [event for event in events if sequence(event) is None or sequence(event) > floor]

    @staticmethod
    def _fuse(weights: dict[str, float]) -> float:
        remaining = 1.
        for confidence in weights.values():
            if confidence > 0.:
                remaining *= 1.-min(1., max(0., confidence))
        return 1.-remaining

    @staticmethod
    def _corpse_field_changed(before: dict, after: dict, corpse_guid: str | None,
                              field: str, *, true_to_false: bool = False) -> bool:
        old, new = before.get("target") or {}, after.get("target") or {}
        if corpse_guid and str(old.get("guid") or "") != str(corpse_guid):
            return False
        if new and corpse_guid and str(new.get("guid") or "") != str(corpse_guid):
            return False
        old_value = old.get(field, old.get("is_"+field))
        new_value = new.get(field, new.get("is_"+field)) if new else None
        if true_to_false:
            return old_value is True and new_value is False
        return old_value is not None and new_value is not None and old_value != new_value

    @staticmethod
    def _gained_item_ids(before_inventory: dict, after_inventory: dict) -> set[int]:
        def counts(inventory: dict) -> dict[int, int]:
            result: dict[int, int] = {}
            for row in inventory.get("items") or ():
                if not isinstance(row, dict):
                    continue
                item_id = row.get("item_id", row.get("itemID"))
                if item_id is None or not str(item_id).lstrip("-").isdigit():
                    continue
                result[int(item_id)] = result.get(int(item_id), 0) + int(row.get("count") or 1)
            return result
        before_counts, after_counts = counts(before_inventory), counts(after_inventory)
        return {item_id for item_id, count in after_counts.items()
                if count > before_counts.get(item_id, 0)}

    @staticmethod
    def _objective_signature(state: dict) -> tuple:
        rows = []
        for quest in state.get("active_quests") or ():
            for objective in quest.get("objectives") or ():
                rows.append((str(quest.get("quest_id")),
                             str(objective.get("objective_id") or objective.get("description")),
                             objective.get("current"), objective.get("required"),
                             bool(objective.get("is_complete"))))
        return tuple(sorted(rows))
