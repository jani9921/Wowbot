"""Deterministic M1 policy for selecting an addon-confirmed gossip offer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re


@dataclass(frozen=True)
class QuestOfferSelection:
    """A pure selection result; it never clicks or mutates quest state."""

    rows: tuple[dict[str, Any], ...] = ()
    offered_quest_ids: tuple[str, ...] = ()
    requires_explicit_selection: bool = False
    reason: str = "no_offers"


class QuestOfferSelector:
    """Choose an explicit match, otherwise one addon-confirmed visible offer.

    The addon's row coordinates are authoritative UI evidence.  When several
    AVAILABLE quests are exposed by the same NPC and no primary quest is
    requested, selecting the topmost exported row is deterministic and lets
    the normal accept/verify loop consume the remaining rows one at a time.
    This is not a guessed screen click: every selected row still has an exact
    quest ID and addon-exported coordinate.
    """

    @staticmethod
    def score_option_against_objective(row: dict[str, Any], objective: dict[str, Any] | None) -> float:
        """Score only explicit, addon-backed option/objective correspondences.

        This deliberately avoids fuzzy semantic guessing.  A title match may
        disambiguate two exported offers, but only when both normalized titles
        are non-empty and exactly equal.  Quest identity remains authoritative.
        """
        context = objective or {}
        row_id = str(row.get("quest_id") or "")
        wanted_ids = {
            str(context.get(key) or "")
            for key in ("quest_id", "primary_quest_id", "active_quest_id")
        } - {""}
        if row_id and row_id in wanted_ids:
            return 1.0
        row_title = QuestOfferSelector._normalized_title(row.get("title"))
        wanted_titles = {
            QuestOfferSelector._normalized_title(context.get(key))
            for key in ("quest_title", "objective_title", "title")
        } - {""}
        return .85 if row_title and row_title in wanted_titles else 0.0

    @staticmethod
    def _normalized_title(value: object) -> str:
        return " ".join(re.findall(r"\w+", str(value or "").casefold(), flags=re.UNICODE))

    def select(self, rows: list[dict[str, Any]], requested_quest_id: object | None = None,
               objective: dict[str, Any] | None = None) -> QuestOfferSelection:
        normalized = tuple(sorted(
            (dict(row) for row in rows),
            key=lambda value: (
                0 if str(value.get("gossip_kind") or "").upper() == "COMPLETE" else 1,
                float(value["y"]), float(value["x"]), str(value["quest_id"]),
            )))
        offered = tuple(sorted({str(row["quest_id"]) for row in normalized}))
        requested = str(requested_quest_id) if requested_quest_id is not None else ""
        if requested:
            selected = tuple(row for row in normalized if str(row["quest_id"]) == requested)
            return QuestOfferSelection(selected, offered, False,
                                       "requested_offer" if selected else "requested_offer_not_present")
        if len(offered) == 1:
            return QuestOfferSelection(normalized, offered, False, "only_offer")
        if len(offered) > 1:
            scored = [(self.score_option_against_objective(row, objective), row) for row in normalized]
            best = max((score for score, _ in scored), default=0.0)
            selected = tuple(row for score, row in scored if score == best and score >= .8)
            if len({str(row["quest_id"]) for row in selected}) == 1:
                return QuestOfferSelection(selected, offered, False, "objective_matched_offer")
            # FULL_AI questing may safely take multiple addon-confirmed
            # offers from one NPC.  Select exactly one visible row now; after
            # its ACCEPT transition is verified, the next planning cycle can
            # select the next still-exported row.  Never emit two clicks from
            # one observation.
            return QuestOfferSelection((normalized[0],), offered, False,
                                       "deterministic_visible_offer")
        return QuestOfferSelection()
