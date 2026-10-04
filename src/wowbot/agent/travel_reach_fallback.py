"""Bounded post-arrival localization for TRAVEL/REACH_AREA objectives."""
from __future__ import annotations

from .models import Proposal


class TravelReachFallbackPolicy:
    """After map arrival without credit, localize; never repeat blind MOVE."""

    @staticmethod
    def propose(objective, record, state: dict, search_area: dict) -> list[Proposal]:
        if (state.get("target") or {}).get("guid") or (state.get("mouseover") or {}).get("guid"):
            return []
        raw = getattr(objective, "raw", {}) or {}
        entity = getattr(objective, "target_entity", {}) or {}
        transition = raw.get("transition_required") is True
        if transition:
            capability, purpose = "SEARCH_ENTRANCE", "SEARCH_ENTRANCE"
            query = str(raw.get("entrance_name") or "entrance cave stairs ramp portal")
        elif entity:
            capability, purpose = "SEARCH_LOCAL_ENTITY", "LOCALIZE_REACH_AREA_NPC"
            query = str(entity.get("name") or entity.get("npc_id") or "quest trigger NPC")
        else:
            capability, purpose = "SEARCH_LOCAL_OBJECT", "LOCALIZE_REACH_AREA_TRIGGER"
            query = str(raw.get("trigger_name") or raw.get("description")
                        or "quest sub-area object or trigger")
        return [Proposal.make(
            "SEEK_VISUAL_CUE",
            "A térképi célterület elérve, de nincs credit: korlátos helyi lokalizáció",
            {"purpose": purpose, "search_capability": capability,
             "query": query, "search_area": dict(search_area),
             "quest_id": getattr(record, "quest_id", None),
             "objective_id": getattr(objective, "objective_id", None),
             "objective_type": getattr(objective, "type", None),
             "scan_budget": 4, "time_budget": 22.},
            confidence=max(.55, float(getattr(objective, "confidence", 0.) or 0.)),
            priority=62)]
