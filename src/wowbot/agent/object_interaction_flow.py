"""Evidence-gated orchestration for quest world-object interaction.

This policy owns no input and invents no object semantics.  It connects the
existing location, bounded visual-search and ``OBJECT_USE`` stages by carrying
the objective's explicit identity through active perception.  Addon mouseover
is the confirmation boundary; raw CV candidates remain UNKNOWN.
"""
from __future__ import annotations

from .models import Proposal, words
from .quest_semantics import world_object_subjects


class ObjectInteractionFlow:
    """Compose locate -> local search -> validate -> use -> credit verify."""

    @staticmethod
    def expected_identity(objective) -> dict:
        target = dict(getattr(objective, "target_object", {}) or {})
        raw = getattr(objective, "raw", {}) or {}
        subjects = world_object_subjects({**raw, "description": getattr(objective, "description", "")})
        return {
            "object_id": target.get("object_id"),
            "item_id": target.get("item_id"),
            "expected_tooltips": subjects,
        }

    @staticmethod
    def mouseover_matches(identity: dict, mouseover: dict) -> bool:
        """Accept explicit IDs first; textual identity only when no ID exists."""
        if identity.get("object_id") is not None:
            return str(mouseover.get("object_id")) == str(identity["object_id"])
        if identity.get("item_id") is not None:
            return str(mouseover.get("item_id")) == str(identity["item_id"])
        tooltip = f" {words(str(mouseover.get('tooltip') or '')).strip()} "
        subjects = [words(str(value)).strip() for value in identity.get("expected_tooltips") or ()]
        return bool(tooltip.strip() and any(value and f" {value} " in tooltip for value in subjects))

    def propose_local_search(self, objective, record, search_area: dict) -> list[Proposal]:
        identity = self.expected_identity(objective)
        query = next(iter(identity.get("expected_tooltips") or ()), None)
        query = str(query or identity.get("object_id") or identity.get("item_id")
                    or getattr(objective, "description", "") or "quest world object")
        return [Proposal.make(
            "SEEK_VISUAL_CUE",
            "Quest-object terület elérve: UNKNOWN cue megközelítése és addon-mouseover azonosítás",
            {"purpose": "SEARCH_LOCAL_OBJECT", "search_capability": "SEARCH_LOCAL_OBJECT",
             "query": query, "search_area": dict(search_area),
             "quest_id": getattr(record, "quest_id", None),
             "objective_id": getattr(objective, "objective_id", None),
             "objective_type": getattr(objective, "type", None),
             **identity, "scan_budget": 4, "time_budget": 22.,
             "ready_bbox_height": .09},
            confidence=max(.6, float(getattr(objective, "confidence", 0.) or 0.)),
            priority=66,
            evidence=("objective_search_area_reached", "object_identity_not_yet_confirmed"))]

