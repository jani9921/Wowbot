"""Fail-closed M1 policy for addon-confirmed quest reward choices."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RewardPolicy(StrEnum):
    """DESIGN-062's named policy vocabulary, verbatim."""

    USER_CONFIG = "USER_CONFIG"
    STAT_RULE = "STAT_RULE"
    VALUE_RULE = "VALUE_RULE"
    TEST_FIRST_VALID = "TEST_FIRST_VALID"
    BLOCKED = "BLOCKED"
    # User 2026-10-04: the live quester must not stall in the reward window.
    AUTO = "AUTO"


@dataclass(frozen=True)
class QuestRewardSelection:
    """Pure reward-selection result; no default UI click is ever implied."""

    choice: dict[str, Any] | None = None
    requires_explicit_policy: bool = False
    reason: str = "no_reward_choices"


class QuestRewardSelector:
    """Select only an explicitly requested or objectively unambiguous reward.

    A reward row has material consequences and Retail UI layouts can change.
    The planner consequently needs both a policy decision and the addon's
    exported coordinates for the exact row; either missing input fails closed.
    """

    @staticmethod
    def _usable_rows(choices: object) -> tuple[dict[str, Any], ...]:
        if not isinstance(choices, (list, tuple)):
            return ()
        rows: list[dict[str, Any]] = []
        for raw in choices:
            if not isinstance(raw, dict):
                continue
            index, x, y = raw.get("index"), raw.get("x"), raw.get("y")
            if not isinstance(index, int) or isinstance(index, bool):
                continue
            if not isinstance(x, (int, float)) or isinstance(x, bool):
                continue
            if not isinstance(y, (int, float)) or isinstance(y, bool):
                continue
            if not (0 < float(x) < 1 and 0 < float(y) < 1):
                continue
            rows.append(dict(raw))
        return tuple(sorted(rows, key=lambda row: int(row["index"])))

    def select(self, choices: object, *, choice_index: object | None = None,
               item_id: object | None = None, policy: object | None = None,
               values: dict[Any, float] | None = None) -> QuestRewardSelection:
        rows = self._usable_rows(choices)
        if not rows:
            return QuestRewardSelection(reason="reward_choice_coordinates_unavailable")
        requested_index = str(choice_index) if choice_index is not None else ""
        requested_item = str(item_id) if item_id is not None else ""
        # DESIGN-062: an explicit choice_index/item_id IS the USER_CONFIG
        # policy -- checked first regardless of the `policy` argument, same
        # as before this addition.
        if requested_index:
            choice = next((row for row in rows if str(row["index"]) == requested_index), None)
            return QuestRewardSelection(choice, False,
                                        "requested_reward_index" if choice else "requested_reward_index_not_present")
        if requested_item:
            matches = tuple(row for row in rows if str(row.get("item_id")) == requested_item)
            if len(matches) == 1:
                return QuestRewardSelection(matches[0], False, "requested_reward_item")
            return QuestRewardSelection(reason="requested_reward_item_not_unique_or_not_present")
        policy_name = str(policy or "").upper()
        if policy_name == "FIRST_UNAMBIGUOUS" and len(rows) == 1:
            return QuestRewardSelection(rows[0], False, "only_reward_choice")
        if policy_name == RewardPolicy.STAT_RULE:
            return self._select_by_stat_rule(rows)
        if policy_name == RewardPolicy.VALUE_RULE:
            return self._select_by_value_rule(rows, values)
        if policy_name == RewardPolicy.TEST_FIRST_VALID:
            # Deterministic first-row pick for offline/test harnesses only --
            # "Elesben random valasztas tilos" bans this in a live session;
            # callers must gate it behind an explicit test/offline flag.
            return QuestRewardSelection(rows[0], False, "test_first_valid")
        if policy_name == RewardPolicy.BLOCKED:
            return QuestRewardSelection(reason="reward_selection_explicitly_blocked")
        if policy_name == RewardPolicy.AUTO:
            return self._select_auto(rows)
        return QuestRewardSelection(requires_explicit_policy=True,
                                    reason="reward_selection_policy_required")

    @staticmethod
    def _select_auto(rows: tuple[dict[str, Any], ...]) -> QuestRewardSelection:
        """Deterministic live default (live 2026-10-04: Expeditionary Short
        Sword vs Cudgel stalled the turn-in): usable by this character first,
        then the higher item level, then the higher vendor price (addon
        0.9.53), then the lowest row -- never random."""
        usable = [row for row in rows if row.get("is_usable") is True] or list(rows)

        def number_or(value, fallback=-1.):
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback

        best = max(usable, key=lambda row: (number_or(row.get("item_level")),
                                            number_or(row.get("sell_price")),
                                            -int(row["index"])))
        return QuestRewardSelection(best, False, "auto_usable_item_level_sell_price")

    @staticmethod
    def _select_by_stat_rule(rows: tuple[dict[str, Any], ...]) -> QuestRewardSelection:
        # Real addon-exported field (AIPlayerControllerExport.lua's
        # GetQuestItemInfo `itemLevel`) -- never a fabricated stat proxy.
        usable = [row for row in rows if row.get("is_usable") is True]
        if not usable:
            return QuestRewardSelection(reason="stat_rule_no_usable_rows")
        levels = [row.get("item_level") for row in usable]
        if any(not isinstance(level, (int, float)) or isinstance(level, bool) for level in levels):
            return QuestRewardSelection(reason="stat_rule_missing_item_level")
        best = max(usable, key=lambda row: row["item_level"])
        tied = [row for row in usable if row["item_level"] == best["item_level"]]
        if len(tied) > 1:
            return QuestRewardSelection(reason="stat_rule_tied_item_level")
        return QuestRewardSelection(best, False, "stat_rule_highest_item_level")

    @staticmethod
    def _select_by_value_rule(rows: tuple[dict[str, Any], ...],
                              values: dict[Any, float] | None) -> QuestRewardSelection:
        # This selector has no genuine "value" signal of its own for quest
        # reward choices (unlike vendor items, they carry no price) -- the
        # caller must supply real values (e.g. from its own stat-weighting
        # config), keyed by row `index` or `item_id`. Never invented here.
        if not values:
            return QuestRewardSelection(reason="value_rule_requires_values")
        scored = []
        for row in rows:
            value = values.get(row["index"], values.get(row.get("item_id")))
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return QuestRewardSelection(reason="value_rule_missing_value_for_row")
            scored.append((value, row))
        best_value = max(value for value, _ in scored)
        tied = [row for value, row in scored if value == best_value]
        if len(tied) > 1:
            return QuestRewardSelection(reason="value_rule_tied_value")
        return QuestRewardSelection(tied[0], False, "value_rule_highest_value")
